import argparse
import asyncio
import collections
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import requests
import tqdm
from bs4 import BeautifulSoup

from data_quality import DataQualityError, compare_snapshots, read_snapshot, write_report
from device_resolution import resolve_device, resolve_previous_names
from french_repairability_scraper import FrenchRepairabilityScraper
from ifixit_api_client import IFixitAPIClient
from model_identification import collect_model_identification
from rate_limiter import _RateLimiter
from utils import _DeviceDataUtils

# Configure logging
logger = logging.getLogger(__name__)
log_level = logging.DEBUG if os.getenv("DEBUG") else logging.INFO


class Suppress404Filter(logging.Filter):
    """Filters out HTTP 404 error logs from ifixit_api_client unless in debug mode."""

    def filter(self, record: logging.LogRecord) -> bool:
        if log_level == logging.DEBUG:
            return True
        return not ("ifixit_api_client" in record.name and "HTTP error: 404" in record.getMessage())


logging.basicConfig(level=log_level)
logging.getLogger("ifixit_api_client").addFilter(Suppress404Filter())

type JsonValue = dict[str, "JsonValue"] | list["JsonValue"] | str | int | float | bool | None


def write_json_atomic(path: str, data: object) -> None:
    """
    Atomically writes JSON data to a specified file. This function creates a temporary
    file to ensure that the write operation is safer and minimizes the potential loss
    of data in case of an unexpected event during the write process. The temporary
    file is written in the same directory as the target file, and it replaces the
    target file once the operation completes successfully.

    Args:
        path: The path to the target file.
        data: The JSON-serializable data to be written.
    """
    target = Path(path)
    tmp_dir = target.parent if str(target.parent) else Path(".")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=tmp_dir, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, target)


def _collect_leaf_device_names(node: JsonValue, excluded_keys: set[str] | None = None) -> Iterable[str]:
    """Yields leaf device names under a node.

    A leaf device is represented by:
      - A dict entry with value None: {"Asus ROG Phone 6": None}
      - A string inside a list: {"Some Series": ["Model A", "Model B"]}
      - Nested dicts are traversed recursively.
    """
    excluded = excluded_keys or set()

    def from_dict(d: dict[str, JsonValue]) -> Iterable[str]:
        for k, v in d.items():
            if _DeviceDataUtils.is_metadata_key(k) or k in excluded:
                continue
            if v is None:
                yield k
            elif isinstance(v, dict):
                yield from from_dict(v)
            elif isinstance(v, list):
                yield from from_list(v, parent_key=k)

    def from_list(items: list[JsonValue], parent_key: str | None = None) -> Iterable[str]:
        for it in items:
            if isinstance(it, dict):
                yield from _collect_leaf_device_names(it, excluded)
            elif isinstance(it, str):
                yield it
            elif it is None and parent_key is not None:
                yield parent_key

    if isinstance(node, dict):
        yield from from_dict(node)
    elif isinstance(node, list):
        yield from from_list(node)


def _find_and_collect_for_targets(
    node: JsonValue,
    target_categories: Iterable[str],
    exclude_map: dict[str, set[str]] | None = None,
) -> dict[str, list[str]]:
    """Find target categories in the tree and collect leaf devices under them."""
    targets: set[str] = set(target_categories)
    out: dict[str, list[str]] = {t: [] for t in targets}

    def handle_match(cat: str, value: JsonValue) -> None:
        excluded = exclude_map.get(cat, set())
        leaves = list(_collect_leaf_device_names(value, excluded_keys=excluded))
        if value is None:
            leaves.append(cat)
        out[cat].extend(leaves)

    def dfs(current: JsonValue) -> None:
        if isinstance(current, dict):
            for k, v in current.items():
                if _DeviceDataUtils.is_metadata_key(k):
                    continue
                if k in targets:
                    logger.debug("Found target category: %s", k)
                    handle_match(k, v)
                if isinstance(v, (dict, list)):
                    dfs(v)
        elif isinstance(current, list):
            for item in current:
                dfs(item)

    dfs(node)

    for category, names in out.items():
        seen: set[str] = set()
        unique_ordered = [x for x in names if not (x in seen or seen.add(x))]
        out[category] = sorted(unique_ordered)
    return out


def collect_child_devices(
    data: dict[str, JsonValue],
    target_categories: list[str],
    parent: str = "root",
    depth: int = 0,
    exclude_subtrees: dict[str, Iterable[str]] | None = None,
) -> dict[str, list[str]]:
    """Recursively collects leaf device names for specified categories.

    Walks the hierarchy, finds each target category, and collects leaf device names
    in its subtree, ignoring metadata keys and excluded subtrees.

    Args:
        data: The category hierarchy data (dict).
        target_categories: List of category names (e.g., ['iPhone', 'Android Phone']).
        parent: Parent node name for logging context.
        depth: Recursion depth for logging indentation.
        exclude_subtrees: Mapping of target_category -> keys to skip.

    Returns:
        Dictionary mapping each target category to a sorted list of leaf device names.
    """
    indent = "  " * depth
    logger.debug("%sProcessing node: %s (type: %s)", indent, parent, type(data).__name__)

    if not isinstance(data, dict):
        logger.debug("%sSkipping non-dict node: %s", indent, type(data).__name__)
        return {cat: [] for cat in target_categories}

    exclude_map = {k: set(v) for k, v in (exclude_subtrees or {}).items()}
    results = _find_and_collect_for_targets(data, target_categories, exclude_map=exclude_map)
    for category, devices in results.items():
        logger.debug("%sCollected %d devices for %s", indent, len(devices), category)
    return results


def get_child_devices_for_categories(
    client: IFixitAPIClient,
    categories: list[str],
    exclude_subtrees: dict[str, Iterable[str]] | None = None,
) -> dict[str, list[str]]:
    """Fetch and return child devices for the given categories.

    This version keeps results in memory instead of writing a temporary JSON file.

    Args:
        client: IFixit API client instance.
        categories: Category names to fetch from the hierarchy (e.g., ['iPhone']).
        exclude_subtrees: Mapping of target_category -> iterable of subtree keys to exclude.

    Returns:
        Mapping of category -> list of leaf device names.
    """
    try:
        logger.info("Fetching category hierarchy...")
        data = client.get_category(params={"display": "hierarchy"})
        logger.debug("Category fetched successfully")
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 404:
            logger.debug("Category not found (404), returning empty results")
            data = {}
        else:
            logger.exception("Failed to fetch category")
            data = {}

    logger.info("Collecting child devices...")
    child_devices = collect_child_devices(data, categories, exclude_subtrees=exclude_subtrees)

    for category, devices in child_devices.items():
        logger.debug("Child devices for %s:", category)
        if devices:
            logger.debug(json.dumps(devices, indent=2, ensure_ascii=False))
        else:
            logger.error("No child devices found for %s", category)
    return child_devices


def fetch_teardown_guides(client: IFixitAPIClient) -> dict[str, list[dict[str, object]]]:
    """Fetch all teardown guides grouped by category.

    Retrieves guides with pagination and groups them by category. Each guide keeps its
    title, url, and derived tags from iFixit flags. Dedupe is performed later by (title, url).

    Args:
        client: The IFixitAPIClient instance.

    Returns:
        A dictionary mapping normalized categories to a list of guide dicts:
        {'title': str, 'url': str, 'tags': list[str]}.
    """
    params = {"filter": "teardown", "limit": 200}
    results: dict[str, list[dict[str, object]]] = {}
    lock = threading.Lock()
    offset = 0
    max_workers = 8
    batch_size = 200

    def is_main_teardown(category: str, title: str) -> bool:
        """Check if the guide title matches '<category> Teardown' pattern."""
        normalized_category = _DeviceDataUtils.to_ifixit_title(category).lower()
        normalized_title = _DeviceDataUtils.to_ifixit_title(title).lower()
        expected_title = f"{normalized_category}_teardown"
        return normalized_title == expected_title

    def fetch_page(page_offset: int) -> dict[str, list[dict[str, object]]]:
        """Fetch a single page of guides for the given offset."""
        try:
            page_params = params.copy()
            page_params["offset"] = page_offset
            guides = client.get_guides(params=page_params)
            page_results: dict[str, list[dict[str, object]]] = {}
            for guide in guides:
                if guide.get("url") is None or guide.get("category") is None or guide.get("title") is None:
                    continue
                category = guide["category"]
                raw_flags = guide.get("flags", []) or []
                tags = _DeviceDataUtils.build_tags_from_flags(raw_flags)

                if category not in page_results:
                    page_results[category] = []
                page_results[category].append(
                    {
                        "title": guide["title"],
                        "url": guide["url"],
                        "tags": tags,
                        "difficulty": guide.get("difficulty"),
                    }
                )
            return page_results
        except Exception:
            logger.exception("Failed to fetch offset %d", page_offset)
            raise

    def extend_map(dst: dict[str, list[dict[str, object]]], src: dict[str, list[dict[str, object]]]) -> None:
        for category, guides in src.items():
            if category not in dst:
                dst[category] = []
            dst[category].extend(guides)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            offsets = list(range(offset, offset + batch_size * max_workers, batch_size))
            futures = {executor.submit(fetch_page, off): off for off in offsets}
            page_results: dict[str, list[dict[str, object]]] = {}

            for future in tqdm.tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"Fetching guides (offset {offset})",
                unit="page",
                dynamic_ncols=True,
            ):
                with lock:
                    extend_map(page_results, future.result())

            if not page_results:
                break

            with lock:
                extend_map(results, page_results)

            offset += batch_size * max_workers
            logger.debug("Processed batch, new offset: %d", offset)

    def sort_guides_for_category(category: str, guides: list[dict[str, object]]) -> list[dict[str, object]]:
        """Sort guides with the following rules.

        - Archived guides are always at the bottom (regardless of other flags).
        - Among non-archived, main teardowns (matching '<category> Teardown') come first.
        - Within the same bucket, 'starred' comes before 'user_contributed', then others.
        - Final tiebreakers: title (case-insensitive), then url.
        - Dedupe by (title, url).

        Args:
            category: The category name.
            guides: Guides for the category.

        Returns:
            A stable, deduplicated, and sorted list of guides.
        """
        # Dedupe by (title, url).
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, object]] = []
        for g in guides:
            title = str(g.get("title", "") or "").strip()
            url = str(g.get("url", "") or "").strip()
            if not title or not url:
                continue
            key = (title, url)
            if key in seen:
                continue
            seen.add(key)
            # Ensure tags list exists.
            tags = g.get("tags") or []
            g["tags"] = list(tags) if isinstance(tags, list) else []
            unique.append(g)

        def key_fn(g: dict[str, object]) -> tuple[int, int, int, str, str]:
            title = str(g["title"])
            url = str(g["url"])
            tags = list(g.get("tags", []))
            archived_bucket = 1 if "archived" in tags else 0  # archived last
            # Main bucket only matters for non-archived.
            main_bucket = 1
            if archived_bucket == 0 and is_main_teardown(category, title):
                main_bucket = 0
            tag_rank = _DeviceDataUtils.tag_priority(tags) if archived_bucket == 0 else 2
            return archived_bucket, main_bucket, tag_rank, title.lower(), url

        unique.sort(key=key_fn)
        return unique

    # Sort guides for each category.
    for category in list(results.keys()):
        results[category] = sort_guides_for_category(category, results[category])

    # Build normalized lookup to make matching resilient.
    normalized_results: dict[str, list[dict[str, object]]] = {
        _DeviceDataUtils.normalize_key(category): guides for category, guides in results.items()
    }

    logger.info("Fetched %d categories with teardown guides", len(results))
    return normalized_results


def print_device_data(
    client: IFixitAPIClient,
    devices: list[str],
    french_scraper: FrenchRepairabilityScraper,
    output_file: str | None = None,
    previous_devices: list[dict] | None = None,
) -> None:
    """Fetches and prints device repairability scores and guide URLs concurrently."""
    logger.info("Fetching teardown guides for matching...")
    teardown_guides = fetch_teardown_guides(client)

    def dedupe(seq: list[str]) -> list[str]:
        seen: set[str] = set()
        return [d for d in seq if not (d in seen or seen.add(d))]

    unique_devices = dedupe(devices)
    model_identifications = {}
    device_identities = {}
    previous_by_name = {row["name"]: row for row in previous_devices or []}
    if not unique_devices:
        logger.warning("No devices provided.")
        return

    def _fetch_score(
        device_name: str, max_retries: int = 3, base_backoff: float = 0.75
    ) -> tuple[str, str, float | None, str | None, str | None, str | None]:
        ifixit_title = _DeviceDataUtils.to_ifixit_title(device_name)
        for attempt in range(max_retries):
            fetching_device = True
            try:
                if device_name in renamed:
                    data, namespace, ifixit_title, redirects, aliases = renamed[device_name]
                else:
                    previous_namespace = previous_by_name.get(device_name, {}).get("wiki_namespace", "CATEGORY")
                    data, namespace, ifixit_title, redirects = resolve_device(client, ifixit_title, previous_namespace)
                    aliases = []
                fetching_device = False
                device_identities[device_name] = {
                    "wikiid": data["wikiid"],
                    "wiki_namespace": namespace,
                    "previous_names": aliases,
                    "redirects": redirects,
                    "source_status": "verified",
                }
                repairability_score = data.get("repairability_score")
                manufacturer = _DeviceDataUtils.device_brand(data)
                if namespace == "CATEGORY":
                    variants = client.get_category_variants(ifixit_title)
                    if not isinstance(variants, dict) or not isinstance(variants.get("topic_variants"), list):
                        raise DataQualityError(f"Invalid model variants response for {device_name}")
                else:
                    variants = None
                model_identifications[device_name] = collect_model_identification(
                    data, variants, manufacturer, ifixit_title, namespace=namespace
                )

                path = "Device" if namespace == "CATEGORY" else "Wiki"
                repair_link = f"https://www.ifixit.com/{path}/{ifixit_title}"
                return (
                    device_name,
                    ifixit_title,
                    repairability_score,
                    manufacturer,
                    repair_link,
                    None,
                )
            except Exception as e:
                response = getattr(e, "response", None)
                status_code = getattr(response, "status_code", None) if response is not None else None
                retry_after = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
                sleep_s = float(retry_after) if retry_after else base_backoff * (2**attempt)
                if status_code in {429, 500, 502, 503, 504} and attempt < max_retries - 1:
                    time.sleep(sleep_s)
                    continue
                if status_code == 404 and fetching_device:
                    device_identities[device_name] = {
                        "source_status": "not_found",
                        "source_url": getattr(response, "url", None),
                    }
                    logger.warning("Device removed from source (HTTP 404): %s", device_name)
                    return device_name, ifixit_title, None, None, None, None
                logger.error(
                    "Failed to fetch repairability score",
                    exc_info=e,
                    extra={"device": device_name},
                )
                return device_name, ifixit_title, None, None, None, str(e)
        return device_name, ifixit_title, None, None, None, "Max retries exceeded"

    def partition_results(
        rows: list[tuple[str, str, float | None, str | None, str | None, str | None]],
    ) -> tuple[list[tuple[str, str, float | None, str | None, str | None]], list[tuple[str, str]]]:
        with_score = [(n, t, s, brand, link_) for n, t, s, brand, link_, err in rows if s is not None]
        without_score = [(n, t) for n, t, s, _brand, _link, err in rows if s is None]
        with_score.sort(key=lambda x: x[0])
        return with_score, without_score

    budget = getattr(client, "rate_limiter", None)
    max_workers = min(32, max(8, math.ceil(budget.maximum))) if isinstance(budget, _RateLimiter) else 8
    renamed = resolve_previous_names(client, previous_devices, unique_devices)

    results: list[tuple[str, str, float | None, str | None, str | None, str | None]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_fetch_score, name): name for name in unique_devices}
        for fut in tqdm.tqdm(
            as_completed(future_map),
            total=len(future_map),
            desc="Fetching scores",
            unit="device",
            dynamic_ncols=True,
        ):
            results.append(fut.result())

    with_score, without_score = partition_results(results)
    french_scraper.set_api_model_identifications(model_identifications)

    def print_outputs() -> None:
        if without_score:
            logger.info("Devices without a repairability score (or failed to fetch):")
            for name, title in sorted(without_score, key=lambda x: x[0]):
                logger.info("- %s (%s)", name, title)
        logger.info("Repairability scores for devices:")
        for name, title, score, _brand, _link in with_score:
            teardown_items = teardown_guides.get(_DeviceDataUtils.normalize_key(name), [])
            if teardown_items:
                titles_and_urls = [
                    f"{g['title']} ({', '.join(g.get('tags', []))}) : {g['url']}" for g in teardown_items
                ]
                logger.info("- %s (%s): %s, Teardown URLs: %s", name, title, score, titles_and_urls)
            else:
                logger.warning("- %s (%s): %s, No teardown URLs found", name, title, score)
        logger.info("Summary:")
        logger.info("- Devices with a repairability score: %d", len(with_score))
        logger.info("- Total devices processed: %d", len(results))
        matched = sum(
            1 for name, _t, _s, _b, _l in with_score if _DeviceDataUtils.normalize_key(name) in teardown_guides
        )
        logger.info("- Devices with matched teardown URLs: %d", matched)

    def create_device_entry(name, title, score, brand, link, teardown_guides):
        model_identity = model_identifications.get(name)
        french_match = french_scraper.match_device(
            {"name": name, "title": title, "brand": brand, "model_identification": model_identity}
        )
        return {
            "name": name,
            "title": title,
            "repairability_score": score,
            "brand": brand,
            "link": link,
            "teardown_urls": [
                {
                    "title": guide["title"],
                    "url": guide["url"],
                    "tags": guide.get("tags", []),
                    "difficulty": guide.get("difficulty"),
                }
                for guide in teardown_guides.get(_DeviceDataUtils.normalize_key(name), [])
            ],
            "france_repairability_score": french_match["score"],
            "france_repairability": french_match,
            "model_identification": model_identity,
            **device_identities.get(name, {}),
        }

    print_outputs()

    if output_file:
        try:
            # Build payload including devices with and without a repairability score
            # Start with all devices that returned data (including those with score=None)
            existing_keys = set()
            all_entries = []
            for name, title, score, brand, link, error in results:
                entry = create_device_entry(name, title, score, brand, link, teardown_guides)
                if error:
                    entry["import_error"] = f"{name}: device fetch failed: {error}"
                all_entries.append(entry)
                existing_keys.add((name, title))

            # Also include devices that failed (e.g., 404) so they appear as well
            # without duplicating already present entries from results list above.
            for name, title in without_score:
                if (name, title) not in existing_keys:
                    all_entries.append(create_device_entry(name, title, None, None, None, teardown_guides))

            all_entries.sort(key=lambda d: ((d.get("brand") or ""), d["name"], d["title"]))

            rubric_versions = get_rubric_versions_for_devices(client)
            scorecard_map = {entry["device_url"]: entry["scorecard_version"] for entry in rubric_versions}

            updated_entries = []
            for entry in all_entries:
                scorecard_version = scorecard_map.get(entry.get("link"))
                if scorecard_version:
                    new_entry = collections.OrderedDict()
                    for k, v in entry.items():
                        new_entry[k] = v
                        if k == "repairability_score":
                            new_entry["scorecard_version"] = scorecard_version
                    updated_entries.append(new_entry)
                else:
                    updated_entries.append(entry)

            write_json_atomic(output_file, updated_entries)
            logger.info("Wrote %d devices (including those without scores) to: %s", len(all_entries), output_file)
        except Exception:
            logger.exception("Failed to write results to %s", output_file)
            raise


def generate_rubric_json(client: IFixitAPIClient, output_file: str = "rubric.json") -> None:
    """
    Scrape iFixit wiki pages to generate rubric.json with version-specific criteria, weights, notes,
    factors not considered, and revisions.

    Args:
        client: IFixitAPIClient instance for fetching wiki pages.
        output_file: Path to write the JSON output (default: 'rubric.json').
    """

    def fetch_page(version: str) -> BeautifulSoup | None:
        """Fetch and parse a wiki page for a given version using IFixitAPIClient."""
        title = f"Repairability_Scoring_Rubric_v{version}"
        try:
            data = client.get_wiki("WIKI", title)
            if not isinstance(data, dict) or not isinstance(data.get("contents_rendered"), str):
                raise DataQualityError(f"Invalid rubric API response for {title}")
            soup = BeautifulSoup(data["contents_rendered"], "html.parser")
            heading = soup.new_tag("h1")
            heading.string = data.get("display_title") or data.get("title") or ""
            soup.insert(0, heading)
            return soup
        except requests.RequestException as e:
            response = getattr(e, "response", None)
            if response is None or response.status_code != 404:
                raise
            logger.error(f"Failed to fetch wiki page for version {version}: {e}")
            return None

    def is_valid_page(soup: BeautifulSoup | None) -> bool:
        if not soup:
            return False
        text = soup.get_text(" ")
        heading = soup.find("h1")
        return bool(
            heading
            and re.search(r"Repairability Scoring Rubric", heading.get_text(" "), re.IGNORECASE)
            and not re.search(r"there is no article with this exact name", text, re.IGNORECASE)
        )

    def iter_versions(start: str = "1.0", step: str = "0.1", max_steps: int = 100):
        cur = Decimal(start)
        inc = Decimal(step)
        for _ in range(max_steps):
            yield f"{cur:.1f}"
            cur += inc

    versions: list[str] = []
    criteria_names = [
        "Design for Repair",
        "Service Manual",
        "Parts Availability",
        "Parts Availability & Cost",
        "Unique Product Identifier",
        "Parts Pairing",
        "Software Updates",
    ]
    criteria = [
        {"name": name, "included": [False] * len(versions), "weights": {}, "notes": {}} for name in criteria_names
    ]
    factors_not_considered: list[dict[str, object]] = []
    revisions: list[dict[str, object]] = []

    for version in iter_versions(start="1.0", step="0.1", max_steps=100):
        logger.info(f"Fetching rubric for version {version}...")
        soup = fetch_page(version)
        if not soup:
            logger.warning(f"Skipping version {version} due to fetch failure")
            continue

        if not is_valid_page(soup):
            logger.debug("Skipping unavailable rubric version %s", version)
            continue

        versions.append(version)
        for c in criteria:
            c["included"].append(False)

        # Extract Scoring Factors
        scoring_factors = []
        scoring_heading = soup.find("p", string=re.compile("Scoring Factors", re.IGNORECASE))
        if scoring_heading:
            table = scoring_heading.find_next("table")
            if table:
                table_rows = table.find_all("tr")
                if not table_rows:
                    raise ValueError(f"Rubric v{version} has an empty scoring table")
                headers = [cell.get_text(" ", strip=True).casefold() for cell in table_rows[0].find_all(["th", "td"])]
                if len(headers) != 3 or headers[1:] != ["weight", "note"]:
                    raise ValueError(f"Rubric v{version} scoring columns changed: {headers}")
                rows = table_rows[1:]
                for row in rows:
                    cells = row.find_all("td")
                    if cells and len(cells) != 3:
                        raise ValueError(f"Rubric v{version} contains an unrecognized scoring row")
                    if len(cells) >= 3:  # Expect criterion, weight, note
                        criterion = cells[0].text.strip()
                        weight = cells[1].text.strip()
                        note = cells[2].text.strip()
                        scoring_factors.append({"criterion": criterion, "weight": weight, "note": note})

        if not scoring_factors:
            raise ValueError(
                f"Rubric v{version} has no recognizable scoring table; refusing to publish incomplete data"
            )

        # New criteria must appear automatically, with earlier versions marked as absent.
        known_names = {c["name"].casefold() for c in criteria}
        for factor in scoring_factors:
            name = re.sub(r"\s*\(if any\)", "", factor["criterion"], flags=re.IGNORECASE).strip()
            if name.casefold() not in known_names:
                criteria.append({"name": name, "included": [False] * len(versions), "weights": {}, "notes": {}})
                known_names.add(name.casefold())

        # Update criteria inclusion, weights, and notes
        for criterion in criteria:
            for sf in scoring_factors:
                # Normalize criterion name (e.g., "Service Manual (if any)" -> "Service Manual")
                sf_criterion = re.sub(r"\s*\(if any\)", "", sf["criterion"], flags=re.IGNORECASE).strip()
                if criterion["name"].lower() == sf_criterion.lower():
                    criterion["included"][-1] = True
                    criterion["weights"][version] = sf["weight"]
                    criterion["notes"][version] = sf["note"]

        # Extract Factors Not Considered
        fnc_items = []
        fnc_heading = soup.find("p", string=re.compile("Factors Not Considered", re.IGNORECASE))
        if fnc_heading:
            table = fnc_heading.find_next("table")
            if table:
                rows = table.find_all("tr")  # Include all rows
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 2:  # Expect criterion, note
                        note = cells[1].text.strip()
                        fnc_items.append(note)
        factors_not_considered.append({"version": version, "items": fnc_items})

        # Extract Revisions
        rev_items = []
        rev_heading = soup.find("p", string=re.compile("Revisions( From Previous Version)?", re.IGNORECASE))
        if rev_heading:
            table = rev_heading.find_next("table")
            if table:
                rows = table.find_all("tr")  # Include all rows
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        note = cells[1].text.strip()
                        # Include "Initial release" only for v1.0
                        if note.lower() != "initial release" or version == "1.0":
                            topic = cells[0].get_text(" ", strip=True)
                            rev_items.append(
                                f"{topic}: {note}" if topic and topic.casefold() not in {"none", "n/a"} else note
                            )
        revisions.append({"version": version, "items": rev_items})

    if not versions:
        raise ValueError("No rubric versions fetched; keeping the previous output")
    if Path(output_file).exists():
        previous = json.loads(Path(output_file).read_text(encoding="utf-8"))
        missing = set(previous.get("versions", [])) - set(versions)
        if missing:
            raise ValueError(f"Previously published rubric versions missing: {sorted(missing)}")

    rubric_data = {
        "versions": versions,
        "criteria": criteria,
        "factors_not_considered": factors_not_considered,
        "revisions": revisions,
    }

    try:
        write_json_atomic(output_file, rubric_data)
        logger.info(f"Wrote rubric data to {output_file}")
    except Exception:
        logger.exception("Failed to write rubric.json")
        raise


def get_rubric_versions_for_devices(client) -> list[dict[str, str]]:
    results = []
    html_new = client.get_repairability_page_html(old_devices=False)
    html_old = client.get_repairability_page_html(old_devices=True)
    for html in [html_new, html_old]:
        soup = BeautifulSoup(html, "html.parser")
        for device_block in soup.find_all(
            "div", class_="wp-block-column is-layout-flow wp-block-column-is-layout-flow"
        ):
            h1 = device_block.find("h1", class_="wp-block-heading")
            if not h1:
                continue
            device_name = h1.get_text(strip=True)
            device_url = None
            img_figure = device_block.find("figure", class_="wp-block-image")
            if img_figure:
                a_tag = img_figure.find("a", href=True)
                if a_tag:
                    device_url = a_tag["href"]

            scorecard_p = device_block.find("p", class_="has-text-align-center has-small-font-size")
            scorecard_version = None
            scorecard_url = None
            if scorecard_p:
                a = scorecard_p.find("a", href=True)
                if a:
                    match = re.search(r"v(\d+\.\d+)", a.get_text())
                    if match:
                        scorecard_version = match.group(1)
                        scorecard_url = a["href"]
            if device_name and scorecard_version and scorecard_url and device_url:
                results.append(
                    {
                        "device_name": device_name,
                        "device_url": device_url,
                        "scorecard_version": scorecard_version,
                        "scorecard_url": scorecard_url,
                    }
                )
    logger.info("Found %d devices with scorecard versions", len(results))
    return results


async def main_async() -> None:
    """Entry point for the script.

    Builds the devices_with_scores.json from iFixit data using in-memory category traversal.
    """
    parser = argparse.ArgumentParser(description="Fetch iFixit device data")
    parser.add_argument(
        "--categories",
        nargs="+",
        default=["iPhone", "Android Phone"],
        help="Categories to fetch",
    )
    parser.add_argument(
        "--scores-output",
        default="devices_with_scores.json",
        help="Output file for scores",
    )
    parser.add_argument(
        "--french-scores-output",
        default="france_devices_with_scores.json",
        help="Output file for French repairability scores",
    )
    parser.add_argument(
        "--generate-rubric",
        action="store_true",
        help="Generate rubric.json from iFixit wiki pages",
    )
    parser.add_argument(
        "--rubric-output",
        default="rubric.json",
        help="Output file for rubric JSON",
    )
    parser.add_argument(
        "--quality-report", default="data_quality_report.json", help="Path for the import quality report"
    )
    parser.add_argument(
        "--api-rate", type=float, default=128, help="Maximum iFixit API requests per second (default: 128)"
    )
    args = parser.parse_args()
    report = {"checked_at": datetime.now(UTC).isoformat(), "status": "running", "errors": [], "warnings": []}
    output_paths = [Path(args.scores_output).resolve(), Path(args.french_scores_output).resolve()]
    if args.generate_rubric:
        output_paths.append(Path(args.rubric_output).resolve())
    if len(set(output_paths)) != len(output_paths) or Path(args.quality_report).resolve() in output_paths:
        raise DataQualityError("Data output paths and quality report path must be distinct")
    try:
        previous_sources = read_snapshot(args.french_scores_output)
        previous_devices = read_snapshot(args.scores_output)
        rate_limiter = _RateLimiter(rate_per_sec=args.api_rate)
        client = IFixitAPIClient(
            log_level=log_level,
            api_key=os.getenv("IFIXIT_TOKEN") or None,
            proxy=os.getenv("IFIXIT_USE_PROXY", "").lower() in {"1", "true", "yes"},
            ca_bundle=os.getenv("IFIXIT_CA_BUNDLE") or None,
            raise_for_status=True,
            rate_limiter=rate_limiter,
        )
        client.get_guides(params={"limit": 1})
        french_scraper = FrenchRepairabilityScraper()
        french_scores = await french_scraper.get_french_repairability_scores()
        # Stage every generated file. A rejected candidate never touches the current outputs.
        with tempfile.TemporaryDirectory(prefix="ifixit-import-") as directory:
            stage = Path(directory)
            if args.generate_rubric:
                old_rubric = Path(args.rubric_output)
                if old_rubric.exists():
                    (stage / "rubric.json").write_bytes(old_rubric.read_bytes())
                generate_rubric_json(client=client, output_file=str(stage / "rubric.json"))
            exclude_subtrees = {"iPhone": {"iPhone Accessories"}}
            child_map = get_child_devices_for_categories(client, args.categories, exclude_subtrees)
            devices = list(dict.fromkeys(name for category in args.categories for name in child_map.get(category, [])))
            if not devices:
                raise DataQualityError("No devices returned by iFixit; refusing to replace published data")
            print_device_data(client, devices, french_scraper, str(stage / "devices.json"), previous_devices)
            candidate_devices = read_snapshot(stage / "devices.json")
            if candidate_devices is None:
                raise DataQualityError("Device generation did not produce a candidate snapshot")
            report = compare_snapshots(previous_sources, french_scores, previous_devices, candidate_devices)
            report["api"] = rate_limiter.stats()
            logger.info("API request statistics: %s", report["api"])
            write_report(args.quality_report, report)
            if report["errors"]:
                raise DataQualityError("; ".join(report["errors"]))
            candidate_devices = [row for row in candidate_devices if row.get("source_status") != "not_found"]
            outputs = [(args.french_scores_output, french_scores), (args.scores_output, candidate_devices)]
            if args.generate_rubric:
                outputs.append((args.rubric_output, json.loads((stage / "rubric.json").read_text())))
            for target, payload in outputs:
                write_json_atomic(target, payload)
            logger.info(
                "Import quality %s; published %d devices and %d French source entries",
                report["status"],
                len(candidate_devices),
                len(french_scores),
            )
    except Exception as error:
        if report["status"] != "blocked":
            report["errors"].append(str(error))
        report["status"] = "blocked"
        write_report(args.quality_report, report)
        raise


def run_main():
    """Run the main async function, handling existing event loops."""
    try:
        # Try to use asyncio.run for standalone execution
        asyncio.run(main_async())
    except RuntimeError as e:
        # If an event loop is already running (e.g., in Jupyter), use the existing loop
        if "cannot run the event loop" in str(e).lower():
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If the loop is running, create a task (suitable for async contexts)
                loop.create_task(main_async())
            else:
                # If the loop exists but isn't running, run the coroutine
                loop.run_until_complete(main_async())
        else:
            raise


if __name__ == "__main__":
    run_main()
