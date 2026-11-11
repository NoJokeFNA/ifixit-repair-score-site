import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

from data_quality import DataQualityError, compare_snapshots, read_snapshot, summarize
from fetch_device_data import main_async


def sources(count=20):
    return [
        {
            "name": f"Model {i}",
            "source_url": f"https://www.indicereparabilite.fr/produit/{i}/",
            "repairability_score": 7.2,
        }
        for i in range(count)
    ]


def devices(count=20):
    return [
        {
            "name": f"Model {i}",
            "brand": "Example",
            "repairability_score": 6,
            "france_repairability_score": 7.2,
            "france_repairability": {"status": "matched", "score": 7.2, "sources": []},
        }
        for i in range(count)
    ]


class ImportComparisonTests(unittest.TestCase):
    def test_wikiid_rename_preserves_metrics_but_real_variant_loss_still_blocks(self):
        before = devices()
        before[0].update(
            {
                "wikiid": 123,
                "model_identification": {
                    "model_numbers": ["SM-A205F"],
                    "variants": [{"name": f"Region {i}", "variant_id": i + 1} for i in range(10)],
                },
            }
        )
        after = deepcopy(before)
        after[0]["name"] = "Renamed model"
        report = compare_snapshots(sources(), sources(), before, after)
        self.assertEqual(report["status"], "passed")
        self.assertTrue(all(metric["lost"] == 0 for metric in report["metrics"].values()))
        self.assertIn("Model 0 → Renamed model", summarize(report))
        after[0]["model_identification"]["variants"] = []
        report = compare_snapshots(sources(), sources(), before, after)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any("10 of 10 named variants disappeared" in error for error in report["errors"]))

    def test_name_similarity_alone_does_not_establish_a_rename(self):
        before, after = devices(), devices()
        before[0]["name"] = "Samsung Galaxy A2000"
        after[0]["name"] = "Samsung Galaxy A20"
        report = compare_snapshots(sources(), sources(), before, after)
        self.assertEqual(report["metrics"]["devices"]["lost"], 1)
        self.assertEqual(report["renames"], [])

    def test_duplicate_wiki_ids_and_ambiguous_rename_claims_block_import(self):
        for collision in ("wikiid", "previous_names"):
            before, after = devices(), devices()
            if collision == "wikiid":
                after[0]["wikiid"] = after[1]["wikiid"] = 123
            else:
                after[0]["previous_names"] = ["Model 0", "Model 1"]
            report = compare_snapshots(sources(), sources(), before, after)
            self.assertEqual(report["status"], "blocked")

    def test_same_name_cannot_hide_an_unverified_wikiid_change(self):
        before, after = devices(), devices()
        before[0]["wikiid"] = 123
        after[0]["wikiid"] = 456
        report = compare_snapshots(sources(), sources(), before, after)
        self.assertEqual(report["status"], "blocked")
        after[0]["redirects"] = [{"wikiid": 123, "namespace": "CATEGORY", "title": "Model_0"}]
        self.assertEqual(compare_snapshots(sources(), sources(), before, after)["status"], "passed")

    def test_first_import_and_unchanged_snapshot_pass(self):
        for old_sources, old_devices in [(None, None), (sources(), devices())]:
            report = compare_snapshots(old_sources, sources(), old_devices, devices())
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["metrics"]["french_scores"]["candidate"], 20)

    def test_source_loss_is_blocked_even_when_total_grows(self):
        after = sources()[2:] + sources(30)[20:]
        report = compare_snapshots(sources(), after, devices(), devices())
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["metrics"]["source_products"], {"previous": 20, "candidate": 28, "lost": 2})

    def test_lost_french_or_ifixit_scores_are_detected(self):
        for field, metric in [
            ("france_repairability_score", "french_scores"),
            ("repairability_score", "ifixit_scores"),
        ]:
            after = devices()
            for row in after[:2]:
                row[field] = None
            report = compare_snapshots(sources(), sources(), devices(), after)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["metrics"][metric]["lost"], 2)

    def test_missing_devices_and_whole_manufacturer_outage_are_detected(self):
        self.assertEqual(compare_snapshots(sources(), sources(), devices(), devices()[2:])["status"], "blocked")
        before, after = devices(100), devices(100)
        for row in before[:3] + after[:3]:
            row["brand"] = "Small brand"
        for row in after[:2]:
            row["france_repairability_score"] = None
        report = compare_snapshots(sources(), sources(), before, after)
        self.assertTrue(any("Small brand" in message for message in report["errors"]))

    def test_small_changes_warn_and_score_updates_are_allowed(self):
        before, after = devices(), devices()
        after[0]["france_repairability_score"] = None
        # Below the global threshold and below 50% of the brand, retain a visible warning.
        report = compare_snapshots(sources(), sources(), before, after)
        self.assertEqual(report["status"], "warning")
        after[0]["france_repairability_score"] = 8.2
        self.assertEqual(compare_snapshots(sources(), sources(), before, after)["status"], "passed")

    def test_invalid_or_empty_sources_are_blocked(self):
        for after in [[], sources() + sources()[:1], [{**sources()[0], "repairability_score": float("nan")}]]:
            self.assertEqual(compare_snapshots(sources(), after, devices(), devices())["status"], "blocked")

    def test_loss_of_model_or_region_evidence_is_detected(self):
        before, after = devices(), devices()
        for row in before:
            row["model_identification"] = {
                "model_numbers": ["A2633"],
                "variants": [{"name": "A2633 Global", "variant_id": 1}],
            }
        for row in after:
            row["model_identification"] = {"model_numbers": [], "variants": []}
        report = compare_snapshots(sources(), sources(), before, after)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["metrics"]["model_identifications"]["lost"], 20)
        self.assertEqual(report["metrics"]["regional_variants"]["lost"], 20)

    def test_non_finite_device_scores_are_blocked(self):
        after = devices()
        after[0]["repairability_score"] = float("nan")
        self.assertEqual(compare_snapshots(sources(), sources(), devices(), after)["status"], "blocked")

    def test_single_device_cannot_silently_lose_most_regional_variants(self):
        before, after = devices(100), devices(100)
        for row in before + after:
            row["model_identification"] = {"variants": [{"name": f"Region {i}", "variant_id": i + 1} for i in range(5)]}
        after[0]["model_identification"]["variants"] = after[0]["model_identification"]["variants"][:1]
        report = compare_snapshots(sources(), sources(), before, after)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any("Model 0: 4 of 5 named variants" in message for message in report["errors"]))

    def test_corrupt_baseline_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "baseline.json"
            self.assertIsNone(read_snapshot(target))
            target.write_text("{}")
            with self.assertRaises(DataQualityError):
                read_snapshot(target)

    def test_summary_contains_actual_losses(self):
        report = compare_snapshots(sources(), sources()[2:], devices(), devices())
        summary = summarize(report)
        self.assertIn("Import quality: blocked", summary)
        self.assertIn("| source_products | 20 | 18 | 2 |", summary)
        self.assertIn("Published data is retained", summary)


class StagedImportTests(unittest.IsolatedAsyncioTestCase):
    async def run_import(self, directory, candidate_sources, candidate_devices, *, rubric_failure=False):
        root = Path(directory)
        for name, payload in [
            ("france.json", sources()),
            ("devices.json", devices()),
            ("rubric.json", {"previous": "rubric"}),
        ]:
            (root / name).write_text(json.dumps(payload))
        before = {name: (root / name).read_bytes() for name in ["france.json", "devices.json", "rubric.json"]}
        argv = [
            "fetch_device_data.py",
            "--french-scores-output",
            str(root / "france.json"),
            "--scores-output",
            str(root / "devices.json"),
            "--generate-rubric",
            "--rubric-output",
            str(root / "rubric.json"),
            "--quality-report",
            str(root / "quality.json"),
        ]

        def build_rubric(*, output_file, **kwargs):
            self.assertEqual(json.loads(Path(output_file).read_text()), {"previous": "rubric"})
            if rubric_failure:
                raise ValueError("rubric parser failed")
            Path(output_file).write_text(json.dumps({"new": "rubric"}))

        def build_devices(client, names, scraper, output_file, previous_devices):
            Path(output_file).write_text(json.dumps(candidate_devices))

        with (
            patch("sys.argv", argv),
            patch("fetch_device_data.IFixitAPIClient"),
            patch(
                "fetch_device_data.FrenchRepairabilityScraper.get_french_repairability_scores",
                new_callable=AsyncMock,
                return_value=candidate_sources,
            ),
            patch("fetch_device_data.get_child_devices_for_categories", return_value={"iPhone": ["Example"]}),
            patch("fetch_device_data.generate_rubric_json", side_effect=build_rubric),
            patch("fetch_device_data.print_device_data", side_effect=build_devices),
        ):
            error = None
            try:
                await main_async()
            except (DataQualityError, ValueError) as exception:
                error = exception
        return root, before, error

    async def test_quality_rejection_preserves_all_three_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root, before, error = await self.run_import(directory, sources()[2:], devices())
            self.assertIsInstance(error, DataQualityError)
            for name, content in before.items():
                self.assertEqual((root / name).read_bytes(), content)
            self.assertEqual(json.loads((root / "quality.json").read_text())["status"], "blocked")

    async def test_http_failure_preserves_all_published_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = devices()
            candidate[0]["import_error"] = "Model 0: device fetch failed: HTTP 404"
            root, before, error = await self.run_import(directory, sources(), candidate)
            self.assertIsInstance(error, DataQualityError)
            for name, content in before.items():
                self.assertEqual((root / name).read_bytes(), content)
            report = json.loads((root / "quality.json").read_text())
            self.assertIn("HTTP 404", report["errors"][0])

    async def test_other_generation_failure_also_preserves_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root, before, error = await self.run_import(directory, sources(), devices(), rubric_failure=True)
            self.assertIsInstance(error, ValueError)
            for name, content in before.items():
                self.assertEqual((root / name).read_bytes(), content)
            self.assertIn("rubric parser failed", (root / "quality.json").read_text())

    async def test_success_publishes_staged_outputs_with_quality_report(self):
        with tempfile.TemporaryDirectory() as directory:
            updated = devices()
            updated[0]["france_repairability_score"] = 8.1
            root, _before, error = await self.run_import(directory, sources(), updated)
            self.assertIsNone(error)
            self.assertEqual(json.loads((root / "devices.json").read_text()), updated)
            self.assertEqual(json.loads((root / "rubric.json").read_text()), {"new": "rubric"})
            self.assertEqual(json.loads((root / "quality.json").read_text())["status"], "passed")

    async def test_report_path_cannot_overwrite_published_data(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data.json"
            target.write_text('[{"previous":true}]')
            with (
                patch(
                    "sys.argv",
                    ["fetch_device_data.py", "--scores-output", str(target), "--quality-report", str(target)],
                ),
                self.assertRaises(DataQualityError),
            ):
                await main_async()
            self.assertEqual(target.read_text(), '[{"previous":true}]')
