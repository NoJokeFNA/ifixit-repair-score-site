import unittest

from french_repairability_scraper import FrenchRepairabilityScraper, FrenchScoreError


class VerifiedModelNumberTests(unittest.TestCase):
    def setUp(self):
        self.scraper = FrenchRepairabilityScraper()

    def row(self, name, model, score=8.6, brand="Samsung"):
        return {
            "name": name,
            "model": model,
            "brand": brand,
            "repairability_score": score,
            "normalized_name": self.scraper.normalize_device_name(name),
            "source_url": "https://www.indicereparabilite.fr/produit/test/",
        }

    def test_exact_hardware_code_disambiguates_network_variants(self):
        self.scraper.french_scores = [
            self.row("Samsung Galaxy A52 4G", "SM-A525FZWGEUH", 8.6),
            self.row("Samsung Galaxy A52 5G", "SM-A526BZBDEUH", 7.2),
        ]
        for name, score, model in [("Samsung Galaxy A52", 8.6, "SM-A525F"), ("Samsung Galaxy A52 5G", 7.2, "SM-A526B")]:
            result = self.scraper.match_device({"name": name})
            self.assertEqual(result["score"], score)
            self.assertEqual(result["match_method"], "model_number")
            self.assertEqual(result["model_numbers"], [model])
            self.assertTrue(result["model_reference_urls"][0].startswith("https://www.samsung.com/"))

    def test_source_model_is_retained_as_evidence(self):
        self.scraper.french_scores = [self.row("Samsung Galaxy A52 4G", "SM-A525F/DS")]
        self.assertEqual(
            self.scraper.match_device({"name": "Samsung Galaxy A52"})["sources"][0]["model"], "SM-A525F/DS"
        )

    def test_hardware_suffixes_and_retailer_ids_do_not_partially_match(self):
        for value in ["SM-A525FN", "SAMGALAXYA52BL", "SM-A525", "SM-A525F-OTHER"]:
            self.scraper.french_scores = [self.row("Other device", value)]
            self.assertIsNone(self.scraper.match_device_to_french_score({"name": "Samsung Galaxy A52"}))

    def test_contradictory_name_or_brand_never_produces_a_score(self):
        for row in [
            self.row("Samsung Galaxy A52 5G", "SM-A525F"),
            self.row("Samsung Galaxy A52", "SM-A526B"),
            self.row("Samsung Galaxy A52", "SM-A525F", brand="Different brand"),
        ]:
            self.scraper.french_scores = [row]
            self.assertIsNone(self.scraper.match_device_to_french_score({"name": "Samsung Galaxy A52"}))

    def test_conflicting_scores_for_same_hardware_are_not_averaged(self):
        self.scraper.french_scores = [
            self.row("Samsung Galaxy A52 4G", "SM-A525F", 8.6),
            self.row("Samsung Galaxy A52 4G", "SM-A525F", 7.2),
        ]
        self.assertEqual(self.scraper.match_device({"name": "Samsung Galaxy A52"})["status"], "conflicting")

    def test_missing_identifier_does_not_become_a_fuzzy_match(self):
        self.scraper.french_scores = [self.row("Samsung Galaxy A52 4G", "SAMGALAXYA52BL")]
        self.assertEqual(self.scraper.match_device({"name": "Samsung Galaxy A52"})["status"], "ambiguous")

    def test_registry_requires_evidence_and_unique_names(self):
        with self.assertRaises(FrenchScoreError):
            FrenchRepairabilityScraper(model_registry=[{"device_names": ["Example"], "model_numbers": ["SM-A525F"]}])
        entry = self.scraper.model_registry[0]
        with self.assertRaises(FrenchScoreError):
            FrenchRepairabilityScraper(model_registry=[entry, entry])
