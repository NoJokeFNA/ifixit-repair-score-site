import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from french_repairability_scraper import FrenchRepairabilityScraper
from model_identification import collect_model_identification, model_numbers

FIXTURES = Path(__file__).parent / "fixtures/model-identification"


def fixture(name):
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return collect_model_identification(data["category"], data["variants"], data["brand"], name)


class APIModelIdentificationTests(unittest.TestCase):
    def test_iphone_keeps_all_five_regional_variants(self):
        identity = fixture("iPhone_13")
        self.assertEqual(identity["model_numbers"], ["A2482", "A2631", "A2633", "A2634", "A2635"])
        self.assertEqual(len(identity["variants"]), 5)
        self.assertIn("A2482 US", [row["name"] for row in identity["variants"]])
        self.assertIn("A2633 Global", [row["name"] for row in identity["variants"]])
        self.assertTrue(any(url.endswith("/topic_variants") for url in identity["reference_urls"]))

    def test_samsung_keeps_dual_sim_region_and_unlocked_suffix(self):
        identity = fixture("Samsung_Galaxy_S21")
        self.assertEqual(len(identity["variants"]), 8)
        self.assertIn("SM-G991U", identity["model_numbers"])
        self.assertIn("SM-G991U1", identity["model_numbers"])
        self.assertIn("SM-G9910", identity["model_numbers"])
        self.assertTrue(any("/DS" in row["name"] for row in identity["variants"]))
        self.assertEqual(model_numbers("SM-G991U1 USA Unlocked", "Samsung"), {"SM-G991U1"})

    def test_fairphone_uses_explicit_identification_when_variant_is_unnamed(self):
        identity = fixture("Fairphone_5")
        self.assertEqual(identity["model_numbers"], ["FP5"])
        self.assertEqual(identity["variant_status"], "empty")
        self.assertEqual(identity["variants"][0]["name"], "")

    def test_legal_company_name_does_not_create_a_false_brand_conflict(self):
        scraper = FrenchRepairabilityScraper()
        scraper.french_scores = [
            {
                "name": "Fairphone 5",
                "normalized_name": "fairphone 5",
                "brand": "Fairphone B.V.",
                "model": "FP5",
                "repairability_score": 9.3,
            }
        ]
        result = scraper.match_device({"name": "Fairphone 5", "model_identification": fixture("Fairphone_5")})
        self.assertEqual(result["score"], 9.3)
        self.assertEqual(result["model_numbers"], ["FP5"])

    def test_inherited_fields_and_comparison_text_are_not_model_evidence(self):
        category = {
            "info": [{"name": "model_number", "value": "A2633", "inheritedFrom": "iPhone"}],
            "contents_raw": "== Background ==\nUnlike the iPhone 13 A2633.\n== Identification ==\nThis is a phone.",
        }
        result = collect_model_identification(category, {"topic_variants": [{"name": ""}]}, "Apple", "Other")
        self.assertEqual(result["model_numbers"], [])

    def test_missing_endpoint_retains_local_structured_model_field(self):
        category = {"info": [{"name": "model_number", "value": "SM-G991B", "inheritedFrom": None}]}
        result = collect_model_identification(category, None, "Samsung", "Samsung_Galaxy_S21")
        self.assertEqual(result["model_numbers"], ["SM-G991B"])
        self.assertEqual(result["variant_status"], "unavailable")
        self.assertEqual(result["variants"], [])

    def test_partial_samsung_model_is_not_a_complete_identifier(self):
        result = collect_model_identification(
            {}, {"topic_variants": [{"name": "SM-G985", "variantid": 1}]}, "Samsung", "S20_Plus"
        )
        self.assertEqual(result["model_numbers"], [])
        self.assertEqual(result["variants"][0]["name"], "SM-G985")

    def test_only_actual_source_models_are_attached_to_a_french_score(self):
        scraper = FrenchRepairabilityScraper()
        scraper.french_scores = [
            {
                "name": "APPLE iPhone 13",
                "normalized_name": "apple iphone 13",
                "brand": "Apple",
                "model": "A2633",
                "repairability_score": 6.2,
            }
        ]
        identity = fixture("iPhone_13")
        result = scraper.match_device({"name": "iPhone 13", "model_identification": identity})
        self.assertEqual(result["score"], 6.2)
        self.assertEqual(result["model_numbers"], ["A2633"])
        self.assertEqual(result["match_method"], "model_number")
        identity["model_numbers"] = ["A2482"]
        result = scraper.match_device({"name": "iPhone 13", "model_identification": identity})
        self.assertIsNone(result["score"])
        self.assertEqual(result["status"], "ambiguous")

    def test_disagreeing_regional_scores_are_not_merged(self):
        scraper = FrenchRepairabilityScraper()
        scraper.french_scores = [
            {
                "name": "APPLE iPhone 13",
                "normalized_name": "apple iphone 13",
                "brand": "Apple",
                "model": model,
                "repairability_score": score,
            }
            for model, score in [("A2482", 6.0), ("A2633", 6.2)]
        ]
        result = scraper.match_device({"name": "iPhone 13", "model_identification": fixture("iPhone_13")})
        self.assertEqual(result["status"], "conflicting")
        self.assertIsNone(result["score"])

    def test_code_and_known_different_model_name_are_ambiguous(self):
        scraper = FrenchRepairabilityScraper()
        base = {
            "brand": "Apple",
            "model_numbers": ["A2403"],
            "reference_urls": ["https://www.ifixit.com/api/2.0/wikis/CATEGORY/iPhone_12/topic_variants"],
        }
        pro = {**base, "model_numbers": ["A2407"]}
        scraper.set_api_model_identifications({"iPhone 12": base, "iPhone 12 Pro": pro})
        scraper.french_scores = [
            {
                "name": "iPhone 12 Pro",
                "normalized_name": "apple iphone 12 pro",
                "brand": "Apple",
                "model": "A2403",
                "repairability_score": 6.2,
            }
        ]
        result = scraper.match_device({"name": "iPhone 12", "model_identification": base})
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["score"])

    def test_collector_preserves_all_variants_in_generated_devices(self):
        from fetch_device_data import print_device_data

        data = json.loads((FIXTURES / "iPhone_13.json").read_text())
        client = Mock()
        client.get_category.return_value = {**data["category"], "repairability_score": 6}
        client.get_category_variants.return_value = data["variants"]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("fetch_device_data.fetch_teardown_guides", return_value={}),
            patch("fetch_device_data.get_rubric_versions_for_devices", return_value=[]),
        ):
            output = Path(directory) / "devices.json"
            print_device_data(client, ["iPhone 13"], FrenchRepairabilityScraper(), str(output))
            identity = json.loads(output.read_text())[0]["model_identification"]
        client.get_category_variants.assert_called_once_with("iPhone_13")
        self.assertEqual(len(identity["variants"]), 5)
        self.assertEqual(len(identity["model_numbers"]), 5)
