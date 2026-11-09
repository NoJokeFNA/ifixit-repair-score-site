import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from french_repairability_scraper import FrenchRepairabilityScraper, FrenchScoreError

FIXTURE = (Path(__file__).parent / "fixtures/french-product.html").read_text()


class FrenchMatchingTests(unittest.TestCase):
    def setUp(self):
        self.scraper = FrenchRepairabilityScraper()

    def rows(self, *items):
        self.scraper.french_scores = [
            {
                "name": name,
                "normalized_name": self.scraper.normalize_device_name(name),
                "repairability_score": score,
                "source_url": f"https://www.indicereparabilite.fr/produit/test-{index}/",
            }
            for index, (name, score) in enumerate(items)
        ]

    def test_cosmetic_variants_match(self):
        pairs = [
            ("Apple iPhone 11 A2221", "iPhone 11"),
            ("APPLE iPhone 12 mini 128Go (PRODUCT)RED", "iPhone 12 Mini"),
            ("Google – Pixel 6 PRO", "Google Pixel 6 Pro"),
            ("XIAOMI Redmi Note 10S 128 Go Blanc", "Xiaomi Redmi Note 10s"),
            ("Samsung Galaxy S20+ 128 Go 5G Bleu", "Samsung Galaxy S20 Plus 5G"),
            ("Samsung Galaxy S20FE 5G Light Violet", "Samsung Galaxy S20 FE 5G"),
            ("SAMSUNG GALAXY Note20 Ultra 5G", "Samsung Galaxy Note 20 Ultra 5G"),
            ("Fairphone FP6", "Fairphone 6"),
            ("Fairphone B.V. Fairphone 5", "Fairphone 5"),
            ("Fairphone FP3+", "Fairphone 3+"),
        ]
        for source, query in pairs:
            with self.subTest(source=source, query=query):
                self.rows((source, 7.2))
                self.assertEqual(self.scraper.match_device_to_french_score({"name": query}), 7.2)

    def test_network_generation_and_model_variants_never_cross_match(self):
        pairs = [
            ("Google Pixel 4a", "Google Pixel 4a 5G"),
            ("Samsung Galaxy A51", "Samsung Galaxy A51 5G"),
            ("Samsung Galaxy A52 4G", "Samsung Galaxy A52 5G"),
            ("Samsung Galaxy S20 FE 4G", "Samsung Galaxy S20 FE 5G"),
            ("Samsung Galaxy S20", "Samsung Galaxy S20 Ultra"),
            ("Samsung Galaxy S20", "Samsung Galaxy S20 Plus"),
            ("iPhone 11", "iPhone 11 Pro"),
            ("iPhone 11 Pro", "iPhone 11 Pro Max"),
            ("iPhone SE 2020", "iPhone SE 2022"),
            ("iPhone SE 2020", "iPhone SE"),
            ("Xiaomi Redmi Note 10", "Xiaomi Redmi Note 10 5G"),
            ("Xiaomi Redmi Note 10", "Xiaomi Redmi Note 10S"),
            ("Fairphone 3", "Fairphone 3+"),
        ]
        for source, query in pairs:
            with self.subTest(source=source, query=query):
                self.rows((source, 7.2))
                self.assertIsNone(self.scraper.match_device_to_french_score({"name": query}))

    def test_network_after_storage_or_in_parentheses_survives(self):
        for source in ["Samsung Galaxy S20+ 128 Go 5G Bleu", "Samsung Galaxy S20+ (5G) 128 Go"]:
            self.assertEqual(self.scraper.normalize_device_name(source), "samsung galaxy s20 plus 5g")

    def test_unspecified_network_cannot_override_conflicting_variant_evidence(self):
        self.rows(("OnePlus 9 Pro 128 Go", 6.0), ("OnePlus 9 Pro 128 Go 5G", 6.8))
        for name in ["OnePlus 9 Pro", "OnePlus 9 Pro 5G"]:
            result = self.scraper.match_device({"name": name})
            self.assertEqual(result["status"], "conflicting")
            self.assertIsNone(result["score"])

    def test_se_generation_from_year_generation_or_exact_model(self):
        for source in [
            "Apple iPhone SE 2e génération A2296",
            "iPhone SE (2020)",
            "iPhone SE 2nd gen",
            "iPhone SE RED 128 Go A2296",
        ]:
            with self.subTest(source=source):
                self.rows((source, 6.2))
                self.assertEqual(self.scraper.match_device_to_french_score({"name": "iPhone SE 2020"}), 6.2)
                self.assertIsNone(self.scraper.match_device_to_french_score({"name": "iPhone SE 2022"}))
                self.assertIsNone(self.scraper.match_device_to_french_score({"name": "iPhone SE"}))

    def test_ambiguous_or_contradictory_se_identity_is_not_matched(self):
        for source in ["iPhone SE RED 128 Go", "iPhone SE 2022 A2296", ""]:
            self.rows((source, 6.2))
            self.assertIsNone(self.scraper.match_device_to_french_score({"name": "iPhone SE 2020"}))
            self.assertIsNone(self.scraper.match_device_to_french_score({"name": "iPhone SE"}))

    def test_conflicting_scores_never_use_majority_or_order(self):
        for scores in [[5.7, 6.0, 6.0], [6.0, 5.7, 6.0], [6.0, 6.0, 5.7]]:
            self.rows(*[("Apple iPhone 12", score) for score in scores])
            result = self.scraper.match_device({"name": "iPhone 12"})
            self.assertEqual(result["status"], "conflicting")
            self.assertIsNone(result["score"])
            self.assertEqual(len(result["sources"]), 3)

    def test_agreeing_variants_retain_evidence_and_zero_is_valid(self):
        self.rows(("Nokia 3.4 Bleu 64 Go", 0), ("Nokia 3.4 Noir 64 Go", 0))
        result = self.scraper.match_device({"name": "Nokia 3.4"})
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["score"], 0)
        self.assertEqual(len(result["sources"]), 2)
        self.assertTrue(all(row["url"].startswith("https://www.indicereparabilite.fr/") for row in result["sources"]))

    def test_invalid_scores_cannot_be_exported(self):
        for value in [None, True, float("nan"), float("inf"), -1, 11, "6.2"]:
            self.rows(("Google Pixel 6", value))
            self.assertIsNone(self.scraper.match_device_to_french_score({"name": "Google Pixel 6"}))

    def test_generated_ifixit_and_french_scores_remain_independent(self):
        from fetch_device_data import print_device_data

        self.rows(("Fairphone 5", 9.3))
        client = Mock()
        client.get_category.return_value = {
            "title": "Fairphone 5",
            "repairability_score": 10,
            "info": [{"name": "Device Brand", "value": "Fairphone"}],
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("fetch_device_data.fetch_teardown_guides", return_value={}),
            patch("fetch_device_data.get_rubric_versions_for_devices", return_value=[]),
        ):
            output = Path(directory) / "devices.json"
            print_device_data(client, ["Fairphone 5"], self.scraper, str(output))
            device = json.loads(output.read_text())[0]
        self.assertEqual(device["repairability_score"], 10)
        self.assertEqual(device["france_repairability_score"], 9.3)
        self.assertEqual(device["france_repairability"]["status"], "matched")


class FrenchScrapingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.scraper = FrenchRepairabilityScraper()

    async def test_real_source_product_and_provenance(self):
        row = (await self.scraper.parse_smartphones(FIXTURE))[0]
        self.assertEqual(row["name"], "Fairphone FP6")
        self.assertEqual(row["normalized_name"], "fairphone 6")
        self.assertEqual(row["repairability_score"], 9.3)
        self.assertEqual(row["model"], "FP6")
        self.assertEqual(row["last_updated"], "24/06/2025")
        self.assertEqual(row["source_url"], "https://www.indicereparabilite.fr/produit/smartphone-fairphone-fp6/")

    async def test_broken_source_is_rejected(self):
        invalid_html = [
            "<html>Challenge or error page</html>",
            FIXTURE.replace("9,30", "NaN"),
            FIXTURE.replace("9,30", "11,00"),
            FIXTURE.replace("9,30", ""),
            FIXTURE.replace("9,30", "-1"),
            FIXTURE.replace("card-title", "renamed-title"),
            FIXTURE.replace("https://www.indicereparabilite.fr/produit/", "https://example.org/"),
        ]
        for html in invalid_html:
            with self.subTest(html=html[:40]), self.assertRaises(FrenchScoreError):
                await self.scraper.parse_smartphones(html)

    async def test_source_score_decimal_separator_and_whitespace(self):
        for value in ["9,30", "9.30", "9,30\u00a0", " 9,30 "]:
            self.assertEqual(
                (await self.scraper.parse_smartphones(FIXTURE.replace("9,30", value)))[0]["repairability_score"], 9.3
            )

    async def test_missing_first_page_does_not_default_to_hardcoded_pages(self):
        self.scraper.fetch_page = AsyncMock(return_value=None)
        with self.assertRaises(FrenchScoreError):
            await self.scraper.get_french_repairability_scores()

    async def test_timeout_is_retried(self):
        session = MagicMock()
        response = MagicMock()
        response.__aenter__ = AsyncMock(side_effect=TimeoutError)
        session.get.return_value = response
        with patch("french_repairability_scraper.asyncio.sleep", new_callable=AsyncMock):
            self.assertIsNone(await self.scraper.fetch_page(session, "https://www.indicereparabilite.fr/", retries=3))
        self.assertEqual(session.get.call_count, 3)

    async def test_http_failure_then_success_is_retried(self):
        session = MagicMock()
        failed, success = MagicMock(), MagicMock()
        failed.status, success.status = 503, 200
        success.text = AsyncMock(return_value="ok")
        attempts = []
        for result in [failed, success]:
            response = MagicMock()
            response.__aenter__ = AsyncMock(return_value=result)
            attempts.append(response)
        session.get.side_effect = attempts
        with patch("french_repairability_scraper.asyncio.sleep", new_callable=AsyncMock):
            self.assertEqual(await self.scraper.fetch_page(session, "https://www.indicereparabilite.fr/"), "ok")
        self.assertEqual(session.get.call_count, 2)

    def page_html(self, total):
        return (
            FIXTURE
            + f'<p class="woocommerce-result-count">Affichage de 1–16 sur {total} résultats</p>'
            + '<a class="page-numbers" href="/page/2/">2</a>'
        )

    async def test_missing_page_or_duplicate_or_incomplete_snapshot_keeps_previous_state(self):
        first = [{"name": str(i), "source_url": f"https://www.indicereparabilite.fr/produit/{i}/"} for i in range(16)]
        for second in [FrenchScoreError("offline"), [], first[:1]]:
            with self.subTest(second=second):
                previous = [{"name": "previous valid snapshot"}]
                self.scraper.french_scores = previous
                self.scraper.fetch_page = AsyncMock(return_value=self.page_html(17))
                self.scraper.parse_smartphones = AsyncMock(return_value=first)
                self.scraper.get_smartphones_from_page = AsyncMock(
                    side_effect=second if isinstance(second, Exception) else None, return_value=second
                )
                with (
                    patch("french_repairability_scraper.asyncio.sleep", new_callable=AsyncMock),
                    self.assertRaises(FrenchScoreError),
                ):
                    await self.scraper.get_french_repairability_scores()
                self.assertIs(self.scraper.french_scores, previous)

    async def test_complete_snapshot_succeeds(self):
        rows = [{"name": str(i), "source_url": f"https://www.indicereparabilite.fr/produit/{i}/"} for i in range(17)]
        self.scraper.fetch_page = AsyncMock(return_value=self.page_html(17))
        self.scraper.parse_smartphones = AsyncMock(return_value=rows[:16])
        self.scraper.get_smartphones_from_page = AsyncMock(return_value=rows[16:])
        with patch("french_repairability_scraper.asyncio.sleep", new_callable=AsyncMock):
            self.assertEqual(len(await self.scraper.get_french_repairability_scores()), 17)

    async def test_unknown_or_inconsistent_pagination_fails(self):
        for html in [FIXTURE, self.page_html(1000), self.page_html(0)]:
            with self.assertRaises(FrenchScoreError):
                self.scraper._pagination(html)

    async def test_source_failure_preserves_published_output_files(self):
        from fetch_device_data import main_async

        with tempfile.TemporaryDirectory() as directory:
            french_output, devices_output = [Path(directory) / name for name in ["france.json", "devices.json"]]
            for output in [french_output, devices_output]:
                output.write_text(json.dumps([{"previous": "valid data"}]))
            argv = [
                "fetch_device_data.py",
                "--french-scores-output",
                str(french_output),
                "--scores-output",
                str(devices_output),
                "--quality-report",
                str(Path(directory) / "quality.json"),
            ]
            with (
                patch("sys.argv", argv),
                patch("fetch_device_data.IFixitAPIClient"),
                patch.object(
                    FrenchRepairabilityScraper,
                    "get_french_repairability_scores",
                    new_callable=AsyncMock,
                    side_effect=FrenchScoreError("offline"),
                ),
                self.assertRaises(FrenchScoreError),
            ):
                await main_async()
            for output in [french_output, devices_output]:
                self.assertEqual(json.loads(output.read_text()), [{"previous": "valid data"}])
