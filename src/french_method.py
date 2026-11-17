"""Refresh the French smartphone calculation grid without executing Excel macros.

The registry publishes ADEME's historic calculation workbook. Its version is a
workbook edition, not a year-based rating assigned to an individual device.
"""

import copy
import hashlib
import io
import json
import math
import re
import unicodedata
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

INDEX_URL = "https://www.indicereparabilite.fr/grilles-de-calcul/"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
SEED = Path(__file__).resolve().parent.parent / "data/french_method.json"


class FrenchMethodError(ValueError):
    """The source cannot be validated; retain the previous published method."""


def _text(value):
    return " ".join(str(value or "").split())


def _fold(value):
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


def discover_grid(html):
    links = []
    for anchor in BeautifulSoup(html, "html.parser").select("a[href]"):
        href = urljoin(INDEX_URL, anchor["href"])
        parsed = urlparse(href)
        label = _fold(anchor.get_text(" ", strip=True) + " " + parsed.path)
        if "smartphone" in label and parsed.path.lower().endswith(".zip"):
            if parsed.scheme != "https" or parsed.netloc != "www.indicereparabilite.fr":
                raise FrenchMethodError("Unexpected French calculation-grid origin")
            links.append(href)
    if len(set(links)) != 1:
        raise FrenchMethodError("Expected exactly one French smartphone calculation grid")
    return links[0]


def _archive(content):
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        if sum(item.file_size for item in archive.infolist()) > 50_000_000:
            raise FrenchMethodError("Calculation archive exceeds the allowed uncompressed size")
        return archive
    except (zipfile.BadZipFile, OSError) as error:
        raise FrenchMethodError("Invalid French calculation archive") from error


def parse_grid(content, previous, source_url):
    outer = _archive(content)
    files = [name for name in outer.namelist() if name.lower().endswith((".xlsm", ".xlsx"))]
    if len(files) != 1:
        raise FrenchMethodError("Expected one smartphone workbook")
    filename = files[0]
    workbook = _archive(outer.read(filename))
    try:
        strings = [
            "".join(node.itertext())
            for node in ET.fromstring(workbook.read("xl/sharedStrings.xml")).findall("s:si", NS)
        ]
        relationships = {
            node.get("Id"): node.get("Target") for node in ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        }
        sheets = ET.fromstring(workbook.read("xl/workbook.xml")).findall("s:sheets/s:sheet", NS)
        summary = next(sheet for sheet in sheets if sheet.get("name") == "NOTE_FINALE")
        rows = []
        rules = {}
        for sheet in sheets:
            target = relationships[sheet.get(REL)]
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            cells = []
            for row in ET.fromstring(workbook.read(path)).findall("s:sheetData/s:row", NS):
                parsed = {}
                for cell in row.findall("s:c", NS):
                    node = cell.find("s:v", NS)
                    value = node.text if node is not None else ""
                    if cell.get("t") == "s" and value:
                        value = strings[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(cell.find("s:is", NS).itertext())
                    formula = cell.find("s:f", NS)
                    parsed[re.sub(r"\d", "", cell.get("r"))] = {
                        "value": _text(value),
                        "formula": formula.text if formula is not None else None,
                    }
                    if value or formula is not None:
                        cells.append([cell.get("r"), formula.text if formula is not None else _text(value)])
                if sheet is summary:
                    rows.append(parsed)
            if re.match(r"C\d_", sheet.get("name", "")) or sheet is summary:
                rules[sheet.get("name")] = cells
    except (ET.ParseError, KeyError, ValueError, StopIteration, AttributeError, IndexError) as error:
        raise FrenchMethodError("Unrecognised French workbook structure") from error

    seed = json.loads(SEED.read_text())
    known = {entry["id"]: entry for entry in seed["criteria"]}
    previous_criteria = {entry["id"]: entry for entry in previous.get("criteria", [])}
    criteria = []
    current = None
    divisor = None
    seen = set()
    for row in rows:
        heading = row.get("A", {}).get("value", "")
        match = re.match(r"critere\s+(\d+)\s*:", _fold(heading))
        if match:
            identifier = match[1]
            if identifier in {entry["id"] for entry in criteria}:
                raise FrenchMethodError("Duplicate French criterion")
            current = copy.deepcopy(known.get(identifier, {"id": identifier, "name": f"Criterion {identifier}"}))
            prior = previous_criteria.get(identifier)
            if prior and prior.get("source_name") and prior["source_name"] != heading:
                current["name"] = f"Criterion {identifier} (updated source wording)"
                current["description"] = "The source wording changed; see the original wording and linked grid."
            current["source_name"] = heading
            current["subcriteria"] = []
            criteria.append(current)
        description = row.get("B", {}).get("value", "")
        sub = re.match(r"^(\d+)(?:\.(\d+))?\.?(?:\s|$)", description)
        if sub:
            if current is None or sub[1] != current["id"]:
                raise FrenchMethodError("Subcriterion has no matching parent criterion")
            identifier = sub[1] + "." + (sub[2] or "1")
            if identifier in seen or row.get("F", {}).get("formula"):
                raise FrenchMethodError("Duplicate or calculated subcriterion coefficient")
            seen.add(identifier)
            try:
                coefficient = float(row["F"]["value"])
            except (KeyError, ValueError) as error:
                raise FrenchMethodError("Missing French coefficient") from error
            if not math.isfinite(coefficient) or not 0 < coefficient <= 10:
                raise FrenchMethodError("Invalid French coefficient")
            translated = next(
                (entry for entry in known.get(current["id"], {}).get("subcriteria", []) if entry["id"] == identifier),
                {"id": identifier, "name": f"Subcriterion {identifier}"},
            )
            translated = copy.deepcopy(translated)
            translated.update(source_name=description, coefficient=coefficient)
            previous_sub = next(
                (
                    entry
                    for entry in previous_criteria.get(current["id"], {}).get("subcriteria", [])
                    if entry["id"] == identifier
                ),
                {},
            )
            if previous_sub.get("source_name") and previous_sub["source_name"] != description:
                translated["name"] = f"Subcriterion {identifier} (updated source wording)"
            current["subcriteria"].append(translated)
        for cell in row.values():
            formula = cell.get("formula") or ""
            match = re.fullmatch(r"ROUND\([A-Z]+\d+/(\d+(?:\.\d+)?),1\)", formula, re.IGNORECASE)
            if match:
                divisor = float(match[1])
    maximum = sum(sub["coefficient"] * 10 for criterion in criteria for sub in criterion["subcriteria"])
    if len(criteria) < 5 or any(not entry["subcriteria"] for entry in criteria) or not divisor:
        raise FrenchMethodError("Incomplete French criteria or final score formula")
    if not math.isclose(maximum / divisor, 10):
        raise FrenchMethodError("French weights and final score scale disagree")
    for criterion in criteria:
        criterion["maximum"] = round(sum(sub["coefficient"] * 10 for sub in criterion["subcriteria"]), 8)
        criterion["weight"] = round(criterion["maximum"] / maximum * 100, 8)
    version = re.search(r"[_ -]V(\d+(?:\.\d+)+)", filename, re.IGNORECASE)
    version = version[1] if version else None
    fingerprint = hashlib.sha256(json.dumps([version, criteria, divisor, rules], sort_keys=True).encode()).hexdigest()
    today = datetime.now(UTC).date().isoformat()
    result = copy.deepcopy(previous)
    result.update(
        criteria=criteria,
        checked_on=today,
        maximum=maximum,
        divisor=divisor,
        grid_version=version,
        grid_filename=filename,
        grid_source=source_url,
        grid_sha256=fingerprint,
    )
    revisions = result.setdefault("grid_revisions", [])
    if not any(entry["sha256"] == fingerprint for entry in revisions):
        revisions.append(
            {
                "sha256": fingerprint,
                "version": version,
                "observed_on": today,
                "source_url": source_url,
                "filename": filename,
                "criteria": copy.deepcopy(criteria),
                "maximum": maximum,
                "divisor": divisor,
            }
        )
    return result


def refresh_french_method(previous, session=None):
    session = session or requests.Session()
    response = session.get(INDEX_URL, timeout=45)
    response.raise_for_status()
    source_url = discover_grid(response.text)
    response = session.get(source_url, timeout=60)
    response.raise_for_status()
    return parse_grid(response.content, previous, source_url)
