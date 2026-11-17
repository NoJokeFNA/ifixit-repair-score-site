"""Retain reviewed calculation-sheet evidence only while the source is unchanged."""

import hashlib
import json
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup

REGISTRY = Path(__file__).resolve().parent.parent / "data/french_source_verifications.json"


def apply_verification(row, evidence, content, referenced):
    row["catalogue_score"] = row["repairability_score"]
    row["calculation_sheet_url"] = evidence["calculation_sheet_url"]
    if not referenced or hashlib.sha256(content).hexdigest() != evidence["sha256"]:
        row["verification"] = "review_needed"
        row["review_reason"] = "Calculation sheet changed or is no longer attached to the product."
        return
    row.update({key: value for key, value in evidence.items() if key not in {"url", "sha256", "score"}})
    row["repairability_score"] = evidence["score"]
    row["score_origin"] = "calculation_sheet"
    row["verification"] = "sheet_checked"


async def verify_known_sources(rows):
    registry = {entry["url"]: entry for entry in json.loads(REGISTRY.read_text())}
    pending = [row for row in rows if row.get("source_url") in registry]
    if not pending:
        return
    async with aiohttp.ClientSession(trust_env=True) as session:
        for row in pending:
            evidence = registry[row["source_url"]]
            # Recheck both the attachment's presence and its exact reviewed bytes.
            async with session.get(row["source_url"], timeout=aiohttp.ClientTimeout(total=45)) as response:
                response.raise_for_status()
                page = BeautifulSoup(await response.text(), "html.parser")
                referenced = any(image.get("src") == evidence["calculation_sheet_url"] for image in page.select("img"))
            async with session.get(
                evidence["calculation_sheet_url"], timeout=aiohttp.ClientTimeout(total=45)
            ) as response:
                response.raise_for_status()
                content = await response.read()
            apply_verification(row, evidence, content, referenced)
