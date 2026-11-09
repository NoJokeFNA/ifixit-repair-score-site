import asyncio
import logging
import math
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
BASE_URL = "https://www.indicereparabilite.fr"
CATEGORY_URL = f"{BASE_URL}/appareils/smartphone/page/{{page}}/"
_RE_MEMORY = re.compile(r"\b\d+\s*(?:go|gb|to|tb)\b", re.IGNORECASE)
_RE_NETWORK = re.compile(r"(?<![a-z])([45])\s*g\b", re.IGNORECASE)
# Remove presentation differences, never model suffixes such as Pro, Plus, Lite or Ultra.
_RE_COLORS = re.compile(
    r"\b(?:red|blue|green|yellow|orange|purple|black|white|gray|brown|pink|violet|vert|foret"
    r"|tropical|gris|interstellaire|blanc|glacier|noir|de minuit|polaire|bleu|corail|rouge|boreal"
    r"|cosmos|celeste|silver|gold|ls deep|light|polar|lavande|argent|cyan)\b",
    re.IGNORECASE,
)
_SE_YEARS = {
    "a1662": "2016",
    "a1723": "2016",
    "a1724": "2016",
    "a2275": "2020",
    "a2296": "2020",
    "a2298": "2020",
    "a2595": "2022",
    "a2782": "2022",
    "a2783": "2022",
    "a2784": "2022",
    "a2785": "2022",
}


class FrenchScoreError(RuntimeError):
    """Source data is unavailable, incomplete or no longer understood."""


class FrenchRepairabilityScraper:
    """Fetch complete source snapshots and match only unambiguous model scores."""

    def __init__(self):
        self.french_scores: list[dict[str, Any]] = []

    async def fetch_page(self, session: aiohttp.ClientSession, url: str, retries: int = 3) -> str | None:
        for attempt in range(retries):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        return await response.text()
                    logger.warning("French source returned HTTP %s for %s", response.status, url)
            except (aiohttp.ClientError, TimeoutError) as error:
                logger.warning("French source request failed for %s: %s", url, error)
            if attempt < retries - 1:
                await asyncio.sleep(attempt + 1)
        return None

    async def parse_smartphones(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        products = soup.select("ul.products li.product")
        if not products:
            raise FrenchScoreError("No smartphone products found; refusing an empty source snapshot")
        smartphones = []
        for product in products:
            name_element = product.select_one("h4.card-title a")
            score_element = product.select_one("div.footer .price h4 span")
            name = name_element.get_text(" ", strip=True) if name_element else ""
            name = re.sub(r"^\s*Smartphone[\s\-]*", "", name, flags=re.IGNORECASE)
            url = name_element.get("href", "") if name_element else ""
            parsed_url = urlparse(url)
            score_text = score_element.get_text(" ", strip=True) if score_element else ""
            score_text = re.sub(r"\s+", "", score_text).replace("€", "").replace(",", ".")
            if not name or parsed_url.scheme != "https" or parsed_url.netloc != "www.indicereparabilite.fr":
                raise FrenchScoreError(f"Missing product identity or invalid source URL: {name!r}")
            if not re.fullmatch(r"\d+(?:\.\d+)?", score_text):
                raise FrenchScoreError(f"Missing or malformed repairability score for {name!r}: {score_text!r}")
            score = float(score_text)
            if not math.isfinite(score) or not 0 <= score <= 10:
                raise FrenchScoreError(f"Out-of-range repairability score for {name!r}: {score}")

            def field(row, product=product):
                element = product.select_one(f"div.card-description table tbody tr:nth-child({row}) strong")
                return element.get_text(" ", strip=True) if element else None

            model = field(2)
            # The SE product name sometimes omits its generation; its exact Apple model ID disambiguates it.
            identity = f"{name} {model or ''}" if re.search(r"\biphone\s*se\b", name, re.IGNORECASE) else name
            smartphones.append(
                {
                    "name": name,
                    "normalized_name": self.normalize_device_name(identity),
                    "brand": field(1),
                    "model": model,
                    "last_updated": field(3),
                    "repairability_score": score,
                    "source_url": url,
                }
            )
        return smartphones

    @staticmethod
    def _pagination(html: str) -> tuple[int, int]:
        soup = BeautifulSoup(html, "html.parser")
        count = soup.select_one(".woocommerce-result-count")
        text = count.get_text(" ", strip=True) if count else ""
        match = re.search(r"\bsur\s+([\d\s\u00a0\u202f]+)\s+r[ée]sultats?", text, re.IGNORECASE)
        if not match:
            raise FrenchScoreError("Cannot verify source product count; source layout may have changed")
        total = int(re.sub(r"\s", "", match.group(1)))
        numbers = [1]
        for item in soup.select(".page-numbers[href]"):
            page = re.search(r"/page/(\d+)/", item.get("href", ""))
            if page:
                numbers.append(int(page.group(1)))
        pages = max(numbers)
        if total <= 0 or total > pages * 16 or total <= (pages - 1) * 16:
            raise FrenchScoreError(f"Inconsistent source pagination: {total} products over {pages} pages")
        return pages, total

    async def get_total_pages(self, session: aiohttp.ClientSession) -> int:
        html = await self.fetch_page(session, CATEGORY_URL.format(page=1))
        if not html:
            raise FrenchScoreError("Cannot fetch the first source page")
        return self._pagination(html)[0]

    async def get_smartphones_from_page(self, session: aiohttp.ClientSession, page_number: int) -> list[dict[str, Any]]:
        html = await self.fetch_page(session, CATEGORY_URL.format(page=page_number))
        if not html:
            raise FrenchScoreError(f"Cannot fetch source page {page_number}")
        return await self.parse_smartphones(html)

    async def get_french_repairability_scores(self) -> list[dict]:
        # Keep the last successful in-memory snapshot intact until every page is verified.
        async with aiohttp.ClientSession(trust_env=True) as session:
            first_html = await self.fetch_page(session, CATEGORY_URL.format(page=1))
            if not first_html:
                raise FrenchScoreError("Cannot fetch the first source page")
            pages, expected_count = self._pagination(first_html)
            first_rows = await self.parse_smartphones(first_html)
            semaphore = asyncio.Semaphore(5)

            async def limited_fetch(page):
                async with semaphore:
                    await asyncio.sleep(0.5)
                    return await self.get_smartphones_from_page(session, page)

            results = await asyncio.gather(
                *(limited_fetch(page) for page in range(2, pages + 1)), return_exceptions=True
            )
            rows = list(first_rows)
            for page, result in enumerate(results, start=2):
                if isinstance(result, BaseException):
                    raise FrenchScoreError(f"Incomplete French source snapshot: page {page} failed") from result
                rows.extend(result)
            urls = {row["source_url"] for row in rows}
            if len(rows) != expected_count or len(urls) != expected_count:
                raise FrenchScoreError(
                    f"Incomplete or duplicated French snapshot: expected {expected_count}, "
                    f"received {len(rows)} rows and {len(urls)} unique products"
                )
            rows.sort(key=lambda row: row["name"].casefold())
            self.french_scores = rows
            logger.info("Verified %s French source products across %s pages", len(rows), pages)
            return rows

    def match_device(self, device: dict) -> dict:
        """Return traceable evidence; conflicting variants never produce a scalar score."""
        key = self.normalize_device_name(device.get("name", ""))
        candidates = [row for row in self.french_scores if key and row.get("normalized_name") == key]
        if candidates:
            # An unqualified listing may describe either network variant. It must
            # not override contradictory evidence for the same model family.
            family = re.sub(r"(?: [45]g)+$", "", key)
            candidates = [
                row
                for row in self.french_scores
                if row.get("normalized_name") in {key, family}
                or (key == family and re.sub(r"(?: [45]g)+$", "", row.get("normalized_name", "")) == family)
            ]
        sources = [
            {
                "name": row["name"],
                "score": row.get("repairability_score"),
                "url": row.get("source_url"),
                "last_updated": row.get("last_updated"),
            }
            for row in candidates
        ]
        values = {source["score"] for source in sources if self._valid_score(source["score"])}
        if not candidates:
            status = "not_found"
        elif len(values) != 1 or any(not self._valid_score(source["score"]) for source in sources):
            status = "conflicting"
        else:
            status = "matched"
        return {"status": status, "score": next(iter(values)) if status == "matched" else None, "sources": sources}

    @staticmethod
    def _valid_score(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and 0 <= value <= 10
        )

    def match_device_to_french_score(self, device: dict) -> float | None:
        return self.match_device(device)["score"]

    def normalize_device_name(self, raw_name: str) -> str:
        """Normalize cosmetic differences while retaining generation, network and model suffixes.

        No fuzzy/prefix matching: an unknown identity stays unknown. Explicit 4G and
        5G are distinct from an unspecified network. Storage/color variants may be
        grouped, but only matching source scores can be published as one value.
        """
        if not raw_name:
            return ""
        text = "".join(c for c in unicodedata.normalize("NFKD", raw_name.casefold()) if not unicodedata.combining(c))
        text = re.sub(r"^\s*smartphone\s*[-–—]?\s*", "", text)
        if re.search(r"\biphone\s*se\b", text):
            years = set(re.findall(r"\b(?:2016|2020|2022)\b", text))
            for code, year in _SE_YEARS.items():
                if re.search(rf"\b{code}\b", text):
                    years.add(year)
            for generation, year in [(1, "2016"), (2, "2020"), (3, "2022")]:
                if re.search(rf"\b{generation}(?:e|eme|er|st|nd|rd)?\s*gen(?:eration)?\b", text):
                    years.add(year)
            # An unspecified SE is not evidence for any particular generation.
            return f"apple iphone se {next(iter(years))}" if len(years) == 1 else ""

        # Network markers can appear after memory or in parentheses; collect them first.
        networks = sorted(set(_RE_NETWORK.findall(text)))
        text = _RE_NETWORK.sub(" ", text)
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.sub(r"[–—\-_/|:]+", " ", text)
        text = re.sub(r"\bs(\d+)\s*\+", r"s\1 plus ", text)
        text = re.sub(r"\b(s\d+)(fe)\b", r"\1 \2", text)
        text = re.sub(r"\bnote\s*(\d+)\b", r"note \1", text)
        text = re.sub(r"\b(redmi\s+note\s+\d+)\s*s\b", r"\1 s", text)
        text = re.sub(r"^fairphone\s+b\.?v\.?\s+", "", text)
        text = re.sub(r"^fairphone\s+fp(\d+)", r"fairphone \1", text)
        memory = _RE_MEMORY.search(text)
        if memory:
            text = text[: memory.start()]
        text = _RE_COLORS.sub(" ", text)
        text = re.sub(r"\ba\d{4}\b", " ", text) if re.search(r"\biphone\b", text) else text
        if re.match(r"^(?:apple\s+)?iphone\b", text):
            text = re.sub(r"^(?:apple\s+)?iphone\b", "apple iphone", text)
        text = " ".join(text.split())
        return " ".join([text, *(f"{network}g" for network in networks)]) if text else ""
