import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from data_quality import DataQualityError, compare_snapshots
from device_resolution import resolve_device, resolve_previous_names
from fetch_device_data import print_device_data
from french_repairability_scraper import FrenchRepairabilityScraper
from utils import _DeviceDataUtils


def page(title="New phone", wikiid=123, raw=""):
    return {"wikiid": wikiid, "title": title, "contents_raw": raw}


def http_error(status):
    response = requests.Response()
    response.status_code = status
    response.url = "https://www.ifixit.com/api/2.0/wikis/CATEGORY/New_phone"
    return requests.HTTPError(f"HTTP {status}", response=response)


class DeviceResolutionTests(unittest.TestCase):
    def test_exact_source_title_preserves_repeated_spaces_and_special_characters(self):
        self.assertEqual(_DeviceDataUtils.to_ifixit_title("Motorola One Fusion  Plus"), "Motorola_One_Fusion__Plus")
        self.assertEqual(
            _DeviceDataUtils.to_ifixit_title("Lenovo (VIBE) K6   K6 Power"), "Lenovo_%28VIBE%29_K6___K6_Power"
        )
        self.assertEqual(_DeviceDataUtils.to_ifixit_title("Phone + / édition"), "Phone_%2B_%2F_%C3%A9dition")

    def test_category_redirect_uses_canonical_title_and_id(self):
        client = Mock()
        client.get_wiki.side_effect = [page("Old phone", 1, "[redirect|Category:New phone]"), page()]
        data, namespace, title, redirects = resolve_device(client, "Old_phone")
        self.assertEqual((data["wikiid"], namespace, title), (123, "CATEGORY", "New_phone"))
        self.assertEqual(redirects, [{"namespace": "CATEGORY", "title": "Old_phone", "wikiid": 1}])
        self.assertEqual(client.get_wiki.call_args.args, ("CATEGORY", "New_phone"))

    def test_explicit_cross_namespace_redirect_is_followed(self):
        client = Mock()
        client.get_wiki.side_effect = [page("Old phone", 1, "[redirect|Wiki:New phone]"), page()]
        self.assertEqual(resolve_device(client, "Old_phone")[1], "WIKI")
        self.assertEqual(client.get_wiki.call_args.args, ("WIKI", "New_phone"))

    def test_loops_unsupported_targets_and_invalid_payloads_are_rejected(self):
        for payload in [page(raw="[redirect|Category:Old phone]"), page(raw="[redirect|User:Someone]"), {}]:
            with self.subTest(payload=payload), self.assertRaises(DataQualityError):
                resolve_device(Mock(get_wiki=Mock(return_value=payload)), "Old_phone")

    def test_http_404_never_guesses_a_wiki_fallback(self):
        client = Mock()
        client.get_wiki.side_effect = http_error(404)
        with self.assertRaises(requests.HTTPError):
            resolve_device(client, "New_phone")
        client.get_wiki.assert_called_once_with("CATEGORY", "New_phone")

    def test_redirect_chain_is_bounded(self):
        client = Mock()
        client.get_wiki.side_effect = [
            page(f"Phone {i}", i + 1, f"[redirect|Category:Phone {i + 1}]") for i in range(6)
        ]
        with self.assertRaisesRegex(DataQualityError, "Too many device redirects"):
            resolve_device(client, "Phone_0")
        self.assertEqual(client.get_wiki.call_count, 6)

    def test_old_name_is_accepted_only_with_explicit_redirect(self):
        client = Mock()
        before = [{"name": "Old phone", "title": "Old_phone"}]
        client.get_wiki.side_effect = [page("Old phone", 1, "[redirect|Wiki:New phone]"), page()]
        resolved = resolve_previous_names(client, before, ["New phone"])
        self.assertEqual(resolved["New phone"][-1], ["Old phone"])
        client.get_wiki.side_effect = None
        client.get_wiki.return_value = page("Old phone", 1)
        self.assertEqual(resolve_previous_names(client, before, ["New phone"]), {})

    def test_removed_old_url_allows_later_wikiid_comparison_but_server_failure_blocks(self):
        before = [{"name": "Old phone", "wikiid": 123}]
        for status in (404, 503):
            client = Mock(get_wiki=Mock(side_effect=http_error(status)))
            if status == 404:
                self.assertEqual(resolve_previous_names(client, before, ["New phone"]), {})
            else:
                with self.assertRaises(requests.HTTPError):
                    resolve_previous_names(client, before, ["New phone"])


class DeviceImportTests(unittest.TestCase):
    def collect(self, client, names, previous=None):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("fetch_device_data.fetch_teardown_guides", return_value={}),
            patch("fetch_device_data.get_rubric_versions_for_devices", return_value=[]),
            patch("fetch_device_data.time.sleep"),
        ):
            output = Path(directory) / "devices.json"
            print_device_data(client, names, FrenchRepairabilityScraper(), str(output), previous)
            return json.loads(output.read_text())

    def test_verified_category_rename_with_intact_variants_passes(self):
        variants = [{"name": f"Region {i}", "variant_id": i + 1} for i in range(10)]
        before = [{"name": "Old phone", "model_identification": {"variants": variants}}]
        client = Mock()
        client.get_wiki.side_effect = [page("Old phone", 1, "[redirect|Category:New phone]"), page()]
        client.get_category_variants.return_value = {
            "topic_variants": [{"name": row["name"], "variantid": row["variant_id"]} for row in variants],
        }
        after = self.collect(client, ["New phone"], before)
        sources = [{"source_url": "https://example.com/phone", "repairability_score": 7}]
        report = compare_snapshots(sources, sources, before, after)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["metrics"]["regional_variants"]["lost"], 0)
        client.get_category_variants.assert_called_once_with("New_phone")

    def test_cross_namespace_move_records_evidence_but_never_copies_old_variants(self):
        before = [
            {
                "name": "Samsung Galaxy A2000",
                "title": "Samsung_Galaxy_A2000",
                "model_identification": {
                    "model_numbers": ["SM-A205F"],
                    "variants": [{"name": f"Region {i}", "variant_id": i + 1} for i in range(10)],
                },
            }
        ]
        client = Mock()
        client.get_wiki.side_effect = [
            page("Samsung Galaxy A2000", 659186, "[redirect|Wiki:Samsung Galaxy A20]"),
            page("Samsung Galaxy A20", 448629),
        ]
        after = self.collect(client, ["Samsung Galaxy A20"], before)
        row = after[0]
        self.assertEqual(row["wikiid"], 448629)
        self.assertEqual(row["wiki_namespace"], "WIKI")
        self.assertEqual(row["link"], "https://www.ifixit.com/Wiki/Samsung_Galaxy_A20")
        self.assertEqual(row["previous_names"], ["Samsung Galaxy A2000"])
        self.assertEqual(row["model_identification"]["variant_status"], "unavailable")
        self.assertEqual(row["model_identification"]["variants"], [])
        client.get_category_variants.assert_not_called()
        sources = [{"source_url": "https://example.com/phone", "repairability_score": 7}]
        report = compare_snapshots(sources, sources, before, after)
        self.assertEqual(report["metrics"]["devices"]["lost"], 0)
        self.assertEqual(report["metrics"]["regional_variants"]["lost"], 10)
        self.assertEqual(report["status"], "warning")
        self.assertTrue(any("WIKI/Samsung_Galaxy_A20" in warning for warning in report["warnings"]))

    def test_device_and_variant_http_errors_are_explicit_import_errors(self):
        for status, variants in [(503, False), (404, True), (503, True)]:
            with self.subTest(status=status, variants=variants):
                client = Mock()
                if variants:
                    client.get_wiki.return_value = page()
                    client.get_category_variants.side_effect = http_error(status)
                else:
                    client.get_wiki.side_effect = http_error(status)
                row = self.collect(client, ["New phone"])[0]
                self.assertIn(f"HTTP {status}", row["import_error"])
                sources = [{"source_url": "https://example.com/phone", "repairability_score": 7}]
                report = compare_snapshots(sources, sources, [row], [row])
                self.assertEqual(report["status"], "blocked")

    def test_real_error_response_triggers_retries(self):
        client = Mock()
        client.get_wiki.side_effect = [http_error(503), page()]
        client.get_category_variants.return_value = {"topic_variants": []}
        row = self.collect(client, ["New phone"])[0]
        self.assertNotIn("import_error", row)
        self.assertEqual(client.get_wiki.call_count, 2)

    def test_malformed_variant_response_blocks_import(self):
        client = Mock()
        client.get_wiki.return_value = page()
        client.get_category_variants.return_value = {"message": "temporarily unavailable"}
        row = self.collect(client, ["New phone"])[0]
        self.assertIn("Invalid model variants response", row["import_error"])

    def test_next_import_remembers_a_verified_wiki_namespace_move(self):
        client = Mock(get_wiki=Mock(return_value=page()))
        previous = [{"name": "New phone", "wikiid": 123, "wiki_namespace": "WIKI"}]
        row = self.collect(client, ["New phone"], previous)[0]
        client.get_wiki.assert_called_once_with("WIKI", "New_phone")
        self.assertEqual(row["source_status"], "verified")
        self.assertEqual(row["link"], "https://www.ifixit.com/Wiki/New_phone")
        client.get_category_variants.assert_not_called()

    def test_confirmed_device_404_is_a_reported_removal_not_an_import_error(self):
        client = Mock(get_wiki=Mock(side_effect=http_error(404)))
        row = self.collect(client, ["New phone"])[0]
        self.assertEqual(row["source_status"], "not_found")
        self.assertNotIn("import_error", row)
        sources = [{"source_url": "https://example.com/phone", "repairability_score": 7}]
        other = {"name": "Intact phone"}
        report = compare_snapshots(sources, sources, [row, other], [row, other])
        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["source_removals"][0]["name"], "New phone")
