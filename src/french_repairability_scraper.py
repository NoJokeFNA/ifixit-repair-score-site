import asyncio
import difflib
import logging
import os
import re
from typing import Optional, Any

import aiohttp
from bs4 import BeautifulSoup

# Configure logging
logger = logging.getLogger(__name__)


class FrenchRepairabilityScraper:
    """Class to scrape and match French repairability scores from indicereparabilite.fr."""

    def __init__(self):
        self.http_proxy = os.getenv('HTTP_PROXY')
        self.https_proxy = os.getenv('HTTPS_PROXY')
        self.french_scores = []

    async def fetch_page(self, session: aiohttp.ClientSession, url: str, retries: int = 3) -> Optional[str]:
        """Fetch a page with retries and error handling."""
        proxy = self.https_proxy if url.startswith(
            'https://') and self.https_proxy else self.http_proxy if url.startswith(
            'http://') and self.http_proxy else None
        for attempt in range(retries):
            try:
                async with session.get(url, proxy=proxy, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        logger.debug(f"Fetched {url} successfully")
                        return html
                    logger.error(f"Failed to fetch {url}: Status {response.status}")
            except aiohttp.ClientError as e:
                logger.error(f"Error fetching {url}: {e}")
            await asyncio.sleep(1)
        logger.warning(f"Failed to fetch {url} after {retries} attempts")
        return None

    async def parse_smartphones(self, html: str) -> list[Any] | None:
        soup = BeautifulSoup(html, "html.parser")
        products = soup.select("ul.products li.product")
        smartphones = []
        for p in products:
            score_elem = p.select_one("div.footer .price h4 span")
            score = None
            if score_elem:
                score_text = score_elem.get_text(strip=True)
                try:
                    score_cleaned = score_text.replace('€', '').replace(',', '.')
                    score = float(score_cleaned)
                except ValueError:
                    product_name = p.select_one("h4.card-title a")
                    product_name = product_name.get_text(strip=True) if product_name else "Unknown"
                    logger.warning(f"Failed to parse score '{score_text}' for product {product_name}")

                smartphone = {
                    "name": (name.get_text(strip=True) if (name := p.select_one("h4.card-title a")) else None),
                    "marque": (marque.get_text(strip=True) if (marque := p.select_one(
                        "div.card-description table tbody tr:nth-child(1) strong")) else None),
                    "modele": (modele.get_text(strip=True) if (modele := p.select_one(
                        "div.card-description table tbody tr:nth-child(2) strong")) else None),
                    "date_calcul": (date_calc.get_text(strip=True) if (date_calc := p.select_one(
                        "div.card-description table tbody tr:nth-child(3) strong")) else None),
                    "score": score,
                }
                smartphones.append(smartphone)
                logger.debug(f"Parsed {len(smartphones)} smartphones from page")
        return smartphones

    async def get_total_pages(self, session: aiohttp.ClientSession) -> int:
        """Determine the total number of pages dynamically."""
        url = "https://www.indicereparabilite.fr/appareils/smartphone/page/1/"
        html = await self.fetch_page(session, url)
        if not html:
            logger.warning("Could not fetch first page to determine total pages. Defaulting to 38.")
            return 38
        soup = BeautifulSoup(html, "html.parser")
        pagination_items = soup.select("ul.page-numbers li a.page-numbers, ul.page-numbers li span.page-numbers")
        logger.debug(f"Found {len(pagination_items)} pagination items")
        page_numbers = []
        for item in pagination_items:
            if item.name == "a":
                href = item.get("href", "")
                match = re.search(r'/page/(\d+)/', href)
                if match:
                    page_numbers.append(int(match.group(1)))
            elif item.name == "span" and "current" in item.get("class", []):
                try:
                    page_numbers.append(int(item.get_text(strip=True)))
                except ValueError:
                    continue
        return max(page_numbers) if page_numbers else 38

    async def get_smartphones_from_page(self, session: aiohttp.ClientSession, page_number: int) -> list[Any] | None:
        """Fetch and parse smartphones from a single page."""
        url = f"https://www.indicereparabilite.fr/appareils/smartphone/page/{page_number}/"
        logger.debug(f"Fetching page {page_number}...")
        html = await self.fetch_page(session, url)
        if html:
            return await self.parse_smartphones(html)
        return []

    async def get_french_repairability_scores(self) -> list[dict]:
        async with aiohttp.ClientSession() as session:
            total_pages = await self.get_total_pages(session)
            logger.info(f"Found {total_pages} pages to scrape.")
            semaphore = asyncio.Semaphore(5)

            async def limited_fetch(page: int) -> list[Any] | None:
                async with semaphore:
                    await asyncio.sleep(0.5)
                    return await self.get_smartphones_from_page(session, page)

            tasks = [limited_fetch(page) for page in range(1, total_pages + 1)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self.french_scores = []
            for result in results:
                if isinstance(result, list):
                    self.french_scores.extend(result)
                else:
                    logger.error(f"Error in task: {result}")
            logger.info(f"Total smartphones found: {len(self.french_scores)}")
            return self.french_scores

    def match_device_to_french_score(self, device: dict) -> Optional[float]:
        """Match a device to its French repairability score using model, name, title, or brand."""
        import difflib
        import re

        def normalize(text: str) -> str:
            if not text:
                return ""
            text = text.lower()
            text = re.sub(r'smartphone\s*', '', text)
            text = re.sub(r'\s*5g|\s*4g|\s*lte', '', text)
            text = re.sub(r'\s*(?:\d+\s*(?:go|gb|tb)\s*)+', '', text)
            text = re.sub(r'\s*(?:noir|blanc|vert|rouge|bleu|jaune|rose|or|argent|gr[ie]s)[a-zéèê]*', '', text)
            text = re.sub(r'\+', ' plus ', text)
            text = re.sub(r'[_-]', ' ', text)
            text = re.sub(r'[^a-z0-9 ]', '', text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()

        def normalize_name(text: str, brand: str) -> str:
            text = normalize(text)
            brand = normalize(brand)
            if brand and text.startswith(brand):
                text = text[len(brand):].strip()
            return text

        def extract_year_from_name(text: str) -> str:
            match = re.search(r'\b(1[0-9])\b', text.lower())  # e.g., "13" from "iPhone 13"
            return match.group(1) if match else ""

        def extract_model_from_name(text: str) -> str:
            # Extract alphanumeric model code at end (e.g., "A2485" from "iPhone 13 Pro Max A2485")
            match = re.search(r'\b[a-z0-9]{4,7}\b$', text.lower())
            return match.group(0) if match else ""

        device_name = normalize_name(device.get("name", ""), device.get("brand", ""))
        device_title = normalize_name(device.get("title", ""), device.get("brand", ""))
        device_brand = normalize(device.get("brand", ""))
        device_model = normalize(device.get("model", ""))
        device_year = extract_year_from_name(device.get("name", "") + " " + device.get("title", ""))
        device_name_model = extract_model_from_name(device.get("name", "") + " " + device.get("title", ""))

        logger.debug(
            f"Matching device: name='{device_name}', title='{device_title}', brand='{device_brand}', model='{device_model}', year='{device_year}', name_model='{device_name_model}'")

        # Step 1: Exact model code matching
        if device_model:
            for french_device in self.french_scores:
                french_modele = normalize(french_device.get("modele", ""))
                if french_modele == device_model and normalize(french_device.get("marque", "")) == device_brand:
                    score = french_device.get("score")
                    if score is not None:
                        logger.info(
                            f"Matched {device.get('name')} to French score: {score} (exact model: {device_model})")
                        return score

        # Step 2: Model code from name matching
        if device_name_model:
            for french_device in self.french_scores:
                french_name_model = extract_model_from_name(french_device.get("name", ""))
                if french_name_model == device_name_model and normalize(
                    french_device.get("marque", "")) == device_brand:
                    score = french_device.get("score")
                    if score is not None:
                        logger.info(
                            f"Matched {device.get('name')} to French score: {score} (name model: {device_name_model})")
                        return score

        # Step 3: Year + exact name matching (very strict)
        best_match = None
        best_ratio = 0.0
        for french_device in self.french_scores:
            french_name = normalize_name(french_device.get("name", ""), french_device.get("marque", ""))
            french_marque = normalize(french_device.get("marque", ""))
            french_year = extract_year_from_name(french_device.get("name", ""))

            brand_match = device_brand == french_marque
            year_match = device_year == french_year

            name_ratio = difflib.SequenceMatcher(None, device_name, french_name).ratio()
            title_ratio = difflib.SequenceMatcher(None, device_title, french_name).ratio()
            max_ratio = max(name_ratio, title_ratio)

            # Only match if year matches and ratio is near-exact (>0.98)
            if brand_match and year_match and max_ratio > 0.98:
                score = french_device.get("score")
                if score is not None and max_ratio > best_ratio:
                    best_match = score
                    best_ratio = max_ratio
                    logger.debug(
                        f"Exact match for {device.get('name')}: score={score}, ratio={max_ratio:.2f}, french_name='{french_name}'")

        if best_match is not None:
            logger.info(f"Matched {device.get('name')} to French score: {best_match} (exact ratio={best_ratio:.2f})")
            return best_match

        logger.debug(f"No exact match found for {device.get('name')} - leaving as null")
        return None


if __name__ == "__main__":
    scraper = FrenchRepairabilityScraper()
    scraper.french_scores = [
        {"name": "Smartphone SAMSUNG GALAXY S21+ 5G", "marque": "SAMSUNG", "modele": "SM-G996Bs",
         "date_calcul": "24/12/2020", "score": 8.5},
        {"name": "Smartphone APPLE iPhone 13", "marque": "APPLE", "modele": None,
         "date_calcul": None, "score": 6.2},
    ]
    print(scraper.match_device_to_french_score(
        {"name": "iPhone 13", "title": "iPhone_13", "brand": "Apple"}))
    print(scraper.match_device_to_french_score(
        {"name": "Samsung Galaxy S21", "title": "Samsung_Galaxy_S21_Plus", "brand": "Samsung"}))
    asyncio.run(scraper.get_french_repairability_scores())
