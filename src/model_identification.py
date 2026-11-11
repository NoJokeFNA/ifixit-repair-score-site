"""Collect full model/region evidence without treating a display name as a model code."""

import re

from bs4 import BeautifulSoup

_MODEL_PATTERNS = {
    "apple": re.compile(r"(?<![A-Z0-9])A\d{4}(?![A-Z0-9])"),
    "samsung": re.compile(r"(?<![A-Z0-9])SM-[A-Z]\d{3}[A-Z0-9]{1,2}(?![A-Z0-9])"),
    "google": re.compile(r"(?<![A-Z0-9])G[A-Z0-9]{4}(?![A-Z0-9])"),
    "fairphone": re.compile(r"(?<![A-Z0-9])FP[1-9]\d?\+?(?![A-Z0-9])"),
    "nokia": re.compile(r"(?<![A-Z0-9])TA-\d{4}(?![A-Z0-9])"),
    "hmd": re.compile(r"(?<![A-Z0-9])TA-\d{4}(?![A-Z0-9])"),
    "motorola": re.compile(r"(?<![A-Z0-9])XT\d{4}-\d+(?![A-Z0-9])"),
}


def model_numbers(value, brand) -> set[str]:
    if not isinstance(value, str) or not isinstance(brand, str):
        return set()
    pattern = _MODEL_PATTERNS.get(brand.strip().casefold())
    return set(pattern.findall(value.upper())) if pattern else set()


def collect_model_identification(
    category: dict, variants_payload, brand: str | None, title: str, *, namespace: str = "CATEGORY"
) -> dict:
    base_url = f"https://www.ifixit.com/api/2.0/wikis/{namespace}/{title}"
    variants_url = f"{base_url}/topic_variants"
    payload_valid = isinstance(variants_payload, dict) and isinstance(variants_payload.get("topic_variants"), list)
    variants, numbers = [], set()
    if payload_valid:
        for variant in variants_payload["topic_variants"]:
            if not isinstance(variant, dict) or not isinstance(variant.get("name"), str):
                continue
            name = variant["name"].strip()
            codes = sorted(model_numbers(name, brand))
            variants.append({"name": name, "variant_id": variant.get("variantid"), "model_numbers": codes})
            numbers.update(codes)
    references = [variants_url] if payload_valid else []
    for entry in category.get("info") or []:
        if (
            isinstance(entry, dict)
            and not entry.get("inheritedFrom")
            and entry.get("name", "").casefold().replace("_", " ") in {"model number", "model numbers"}
        ):
            codes = model_numbers(entry.get("value"), brand)
            if codes:
                numbers.update(codes)
                references.append(base_url)
    # Identification paragraphs can name other phones for comparison. Only read
    # explicit Model/Model number labels, not every code anywhere in the wiki.
    raw = category.get("contents_raw") or ""
    section = re.search(r"(?ims)^==\s*Identification\s*==\s*(.*?)(?=^==|\Z)", raw)
    identification = section.group(1) if section else ""
    text = BeautifulSoup(category.get("description") or "", "html.parser").get_text(" ") + "\n" + identification
    for match in re.finditer(
        r"(?i)\bmodel(?:\s+(?:number|numbers|identifier))?\s*(?:is\s+)?[:*\s]*([^\n.]{1,120})", text
    ):
        # Stay at the start of a model label, so a sentence mentioning an older
        # device further on cannot add that older device's identifier.
        value = match.group(1).strip(" *:()")
        first = re.split(r"\s+", value)[0]
        codes = model_numbers(first, brand)
        if codes:
            numbers.update(codes)
            references.append(base_url)
    for match in re.finditer(r"""(?i)["*]([A-Z0-9+/-]+)["*][^\n.]{0,80}\bfor its model number\b""", identification):
        codes = model_numbers(match.group(1), brand)
        if codes:
            numbers.update(codes)
            references.append(base_url)
    return {
        "brand": brand,
        "model_numbers": sorted(numbers),
        "variants": variants,
        "variant_status": "available"
        if any(row["name"] for row in variants)
        else "empty"
        if payload_valid
        else "unavailable",
        "reference_urls": sorted(set(references)),
    }
