import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from french_method import SEED, FrenchMethodError, discover_grid, parse_grid, refresh_french_method

FIXTURES = Path(__file__).parent / "fixtures"
GRID = (FIXTURES / "french-smartphone-grid.zip").read_bytes()
URL = "https://www.indicereparabilite.fr/wp-content/uploads/2022/11/Grille_reparabilite_smartphone_FR.zip"


def changed_grid(change, version=None):
    outer = zipfile.ZipFile(io.BytesIO(GRID))
    name = outer.namelist()[0]
    workbook = zipfile.ZipFile(io.BytesIO(outer.read(name)))
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in workbook.namelist():
            value = workbook.read(path)
            if path == "xl/worksheets/sheet9.xml":
                value = change(value.decode()).encode()
            archive.writestr(path, value)
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name.replace("V2.0", "V" + version) if version else name, target.getvalue())
    return result.getvalue()


class FrenchMethodTests(unittest.TestCase):
    def setUp(self):
        self.seed = json.loads(SEED.read_text())

    def test_real_grid_coefficients_and_workbook_version_are_extracted(self):
        value = parse_grid(GRID, self.seed, URL)
        self.assertEqual(value["grid_version"], "2.0")
        self.assertEqual(value["divisor"], 10)
        self.assertEqual(value["maximum"], 100)
        self.assertEqual(len(value["criteria"]), 5)
        self.assertEqual([c["weight"] for c in value["criteria"]], [20] * 5)
        self.assertEqual([s["coefficient"] for s in value["criteria"][2]["subcriteria"]], [1, 0.5, 0.3, 0.2])
        self.assertEqual(len(value["grid_revisions"]), 1)
        self.assertNotIn("grid_revisions", self.seed)

    def test_repeated_fetch_does_not_duplicate_a_revision(self):
        previous = parse_grid(GRID, self.seed, URL)
        again = parse_grid(GRID, previous, URL)
        self.assertEqual(again["grid_revisions"], previous["grid_revisions"])

    def test_new_declared_workbook_edition_is_recorded_even_with_same_coefficients(self):
        previous = parse_grid(GRID, self.seed, URL)
        result = parse_grid(changed_grid(lambda xml: xml, "2.1"), previous, URL)
        self.assertEqual(result["grid_version"], "2.1")
        self.assertEqual(len(result["grid_revisions"]), 2)
        self.assertEqual(previous["grid_version"], "2.0")

    def test_changed_coefficients_refresh_without_losing_the_prior_snapshot(self):
        previous = parse_grid(GRID, self.seed, URL)

        def update(xml):
            return xml.replace('r="F18" s="284"><v>0.5</v>', 'r="F18" s="284"><v>0.75</v>')

        # Locate actual cell markup rather than depending on Excel's style index.
        import re

        changed = changed_grid(
            lambda xml: re.sub(
                r'(<c r="F18"[^>]*><v>)0\.5',
                r"\g<1>0.75",
                re.sub(r'(<c r="F19"[^>]*><v>)0\.5', r"\g<1>0.25", xml),
            )
        )
        result = parse_grid(changed, previous, URL)
        self.assertEqual(result["criteria"][1]["subcriteria"][1]["coefficient"], 0.75)
        self.assertEqual(len(result["grid_revisions"]), 2)
        self.assertEqual(previous["criteria"][1]["subcriteria"][1]["coefficient"], 0.5)

    def test_missing_or_invalid_coefficients_are_not_published(self):
        import re

        for replacement in ("", "-1", "NaN", "3"):
            with self.subTest(replacement=replacement):
                content = changed_grid(
                    lambda xml, value=replacement: re.sub(r'(<c r="F16"[^>]*><v>)2', lambda m: m[1] + value, xml)
                )
                with self.assertRaises(FrenchMethodError):
                    parse_grid(content, self.seed, URL)

    def test_new_criterion_is_read_from_the_grid_instead_of_a_fixed_row_count(self):
        import re

        def change(xml):
            xml = re.sub(r'(<c r="F24"[^>]*><v>)2', r"\g<1>1", xml)
            row = (
                '<row r="29"><c r="A29" t="inlineStr"><is><t>CRITÈRE 6 : NOUVEAU</t></is></c>'
                '<c r="B29" t="inlineStr"><is><t>6.1 Nouveau sous-critère</t></is></c>'
                '<c r="F29"><v>1</v></c></row>'
            )
            return xml.replace("</sheetData>", row + "</sheetData>")

        result = parse_grid(changed_grid(change, "2.1"), self.seed, URL)
        self.assertEqual(len(result["criteria"]), 6)
        self.assertEqual(result["criteria"][-1]["subcriteria"][0]["coefficient"], 1)
        self.assertEqual(result["maximum"], 100)
        self.assertEqual(result["criteria"][-1]["weight"], 10)

    def test_missing_source_and_changed_layout_are_errors(self):
        for html in ("<html>offline</html>", '<a href="https://example.com/smartphone.zip">Smartphone</a>'):
            with self.assertRaises(FrenchMethodError):
                discover_grid(html)
        with self.assertRaises(FrenchMethodError):
            parse_grid(b"not a workbook", self.seed, URL)

    def test_discovery_follows_a_new_published_grid_url(self):
        html = (FIXTURES / "french-grid-index.html").read_text().replace("2022/11", "2027/02")
        session = Mock()
        session.get.side_effect = [Mock(text=html), Mock(content=GRID)]
        result = refresh_french_method(self.seed, session)
        self.assertIn("2027/02", result["grid_source"])
        self.assertEqual(session.get.call_count, 2)

    def test_method_failure_preserves_all_staged_import_outputs(self):
        from fetch_device_data import main_async

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / (name + ".json") for name in ("devices", "france", "method", "images", "status")}
            for name, path in paths.items():
                path.write_text(json.dumps(self.seed if name == "method" else []))
            before = {name: path.read_bytes() for name, path in paths.items()}
            args = [
                "collector",
                "--scores-output",
                str(paths["devices"]),
                "--french-scores-output",
                str(paths["france"]),
                "--french-method-output",
                str(paths["method"]),
                "--images-output",
                str(paths["images"]),
                "--status-output",
                str(paths["status"]),
                "--quality-report",
                str(root / "quality.json"),
            ]
            with (
                patch("sys.argv", args),
                patch("fetch_device_data.IFixitAPIClient"),
                patch(
                    "fetch_device_data.FrenchRepairabilityScraper.get_french_repairability_scores",
                    AsyncMock(return_value=[]),
                ),
                patch("fetch_device_data.refresh_french_method", side_effect=FrenchMethodError("source changed")),
                self.assertRaises(FrenchMethodError),
            ):
                import asyncio

                asyncio.run(main_async())
            self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, before)

    def test_successful_import_publishes_the_new_object_outputs_together(self):
        import asyncio

        from fetch_device_data import main_async

        source = {
            "name": "Phone",
            "source_url": "https://www.indicereparabilite.fr/produit/phone/",
            "repairability_score": 7.2,
        }
        device = {
            "name": "Phone",
            "brand": "Example",
            "repairability_score": 6,
            "france_repairability_score": 7.2,
            "france_repairability": {"status": "matched", "score": 7.2, "sources": []},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in [("devices", [device]), ("france", [source]), ("method", self.seed), ("images", {})]:
                (root / f"{name}.json").write_text(json.dumps(value))
            updated_method = {**self.seed, "grid_version": "2.0", "grid_sha256": "new source hash"}
            args = [
                "collector",
                "--scores-output",
                str(root / "devices.json"),
                "--french-scores-output",
                str(root / "france.json"),
                "--french-method-output",
                str(root / "method.json"),
                "--images-output",
                str(root / "images.json"),
                "--status-output",
                str(root / "status.json"),
                "--quality-report",
                str(root / "quality.json"),
            ]

            def build_devices(client, names, scraper, output, previous):
                Path(output).write_text(json.dumps([device]))

            with (
                patch("sys.argv", args),
                patch("fetch_device_data.IFixitAPIClient"),
                patch(
                    "fetch_device_data.FrenchRepairabilityScraper.get_french_repairability_scores",
                    AsyncMock(return_value=[source]),
                ),
                patch("fetch_device_data.refresh_french_method", return_value=updated_method),
                patch("fetch_device_data.build_image_manifest", return_value={"Phone": {"image_id": 1}}),
                patch("fetch_device_data.get_child_devices_for_categories", return_value={"iPhone": ["Phone"]}),
                patch("fetch_device_data.print_device_data", side_effect=build_devices),
            ):
                asyncio.run(main_async())
            self.assertEqual(json.loads((root / "method.json").read_text())["grid_version"], "2.0")
            self.assertEqual(json.loads((root / "images.json").read_text()), {"Phone": {"image_id": 1}})
            self.assertEqual(json.loads((root / "quality.json").read_text())["status"], "passed")
            status = json.loads((root / "status.json").read_text())
            from datetime import datetime

            self.assertIsNotNone(datetime.fromisoformat(status["updated_at"]).tzinfo)
            self.assertEqual(status["devices"], 1)
            self.assertEqual(status["french_sources"], 1)
