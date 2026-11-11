import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from french_repairability_scraper import FrenchRepairabilityScraper, FrenchScoreError

FIXTURES = Path(__file__).parent / "fixtures"
PRODUCT = json.loads((FIXTURES / "french-product-api.json").read_text())


def products(count):
    rows = []
    for index in range(count):
        row = deepcopy(PRODUCT)
        row.update(id=index + 1, permalink=f"https://www.indicereparabilite.fr/produit/phone-{index}/")
        rows.append(row)
    return rows


class FrenchAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_real_api_fixture_matches_all_html_fields(self):
        scraper = FrenchRepairabilityScraper()
        html_rows = await scraper.parse_smartphones((FIXTURES / "french-product.html").read_text())
        self.assertEqual(scraper.parse_api_products([PRODUCT]), html_rows)

    async def test_invalid_scores_currency_and_identity_are_rejected(self):
        for field, value in [
            ("price", "NaN"),
            ("price", "1100"),
            ("price", "-100"),
            ("price", None),
            ("currency_minor_unit", 0),
            ("currency_code", "USD"),
        ]:
            with self.subTest(field=field, value=value):
                row = deepcopy(PRODUCT)
                row["prices"][field] = value
                with self.assertRaises(FrenchScoreError):
                    FrenchRepairabilityScraper().parse_api_products([row])
        row = {**PRODUCT, "permalink": "https://example.com/wrong-source"}
        with self.assertRaises(FrenchScoreError):
            FrenchRepairabilityScraper().parse_api_products([row])

    async def test_complete_api_snapshot_uses_100_products_per_page_and_no_html_fetches(self):
        scraper = FrenchRepairabilityScraper()
        headers = {"x-wp-total": "101", "x-wp-totalpages": "2"}
        rows = products(101)
        scraper.fetch_api = AsyncMock(
            side_effect=[
                ([{"id": 22, "slug": "smartphone", "count": 101}], {}),
                (rows[:100], headers),
                (rows[100:], headers),
            ]
        )
        scraper.fetch_page = AsyncMock()
        result = await scraper.get_french_repairability_scores()
        self.assertEqual(len(result), 101)
        self.assertEqual(scraper.fetch_api.call_count, 3)
        self.assertEqual(scraper.fetch_api.call_args_list[1].args[2]["per_page"], 100)
        scraper.fetch_page.assert_not_called()

    async def test_missing_duplicate_or_changing_api_page_keeps_previous_snapshot(self):
        for mode in ["missing", "duplicate_id", "duplicate_url", "count_changed", "offline"]:
            with self.subTest(mode=mode):
                scraper = FrenchRepairabilityScraper()
                previous = [{"name": "previous valid data"}]
                scraper.french_scores = previous
                rows = products(101)
                headers = {"x-wp-total": "101", "x-wp-totalpages": "2"}
                second, metadata = rows[100:], headers
                if mode == "missing":
                    second = []
                elif mode == "duplicate_id":
                    second[0]["id"] = rows[0]["id"]
                elif mode == "duplicate_url":
                    second[0]["permalink"] = rows[0]["permalink"]
                elif mode == "count_changed":
                    metadata = {**headers, "x-wp-total": "102"}
                last = FrenchScoreError("offline") if mode == "offline" else (second, metadata)
                scraper.fetch_api = AsyncMock(
                    side_effect=[
                        ([{"id": 22, "slug": "smartphone", "count": 101}], {}),
                        (rows[:100], headers),
                        last,
                    ]
                )
                with self.assertRaises(FrenchScoreError):
                    await scraper.get_french_repairability_scores()
                self.assertIs(scraper.french_scores, previous)

    async def test_category_and_pagination_must_agree(self):
        for headers in [
            {},
            {"x-wp-total": "102", "x-wp-totalpages": "2"},
            {"x-wp-total": "101", "x-wp-totalpages": "1"},
        ]:
            scraper = FrenchRepairabilityScraper()
            scraper.fetch_api = AsyncMock(
                side_effect=[
                    ([{"id": 22, "slug": "smartphone", "count": 101}], {}),
                    (products(100), headers),
                ]
            )
            with self.assertRaises(FrenchScoreError):
                await scraper.get_french_repairability_scores()

    async def test_api_http_error_is_retried_and_body_is_not_logged(self):
        session = MagicMock()
        failed, success = MagicMock(), MagicMock()
        failed.raise_for_status.side_effect = aiohttp.ClientError("HTTP 503")
        success.json = AsyncMock(return_value=[PRODUCT])
        success.headers = {"X-WP-Total": "1"}
        contexts = []
        for response in [failed, success]:
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=response)
            contexts.append(context)
        session.get.side_effect = contexts
        with patch("french_repairability_scraper.asyncio.sleep", new_callable=AsyncMock):
            rows, headers = await FrenchRepairabilityScraper().fetch_api(session, "https://example.com/api", {})
        self.assertEqual(rows, [PRODUCT])
        self.assertEqual(headers["x-wp-total"], "1")
        self.assertEqual(session.get.call_count, 2)
