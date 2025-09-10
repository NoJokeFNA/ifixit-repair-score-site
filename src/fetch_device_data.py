import argparse
import json
import logging
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from typing import Dict, Iterable, List, Optional, Set, Tuple

import tqdm
from ifixit_api_client import IFixitAPIClient

# Configure logging
logger = logging.getLogger(__name__)
log_level = logging.DEBUG if __import__("os").getenv("DEBUG") else logging.INFO


class Suppress404Filter(logging.Filter):
    """Filters out HTTP 404 error logs from ifixit_api_client unless in debug mode."""

    def filter(self, record: logging.LogRecord) -> bool:
        if log_level == logging.DEBUG:
            return True
        return not ("ifixit_api_client" in record.name and "HTTP error: 404" in record.getMessage())


logging.basicConfig(level=log_level)
logging.getLogger("ifixit_api_client").addFilter(Suppress404Filter())

type JsonValue = Dict[str, "JsonValue"] | List["JsonValue"] | str | int | float | bool | None


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


def _is_metadata_key(key: str) -> bool:
    """Returns whether a key is considered metadata and should be skipped."""
    metadata_keys = {
        "attrs",
        "contents_json",
        "image",
        "inheritedFrom",
        "parts",
        "repairability_score",
        "source_revisionid",
    }
    return key in metadata_keys


def _collect_leaf_device_names(
    node: JsonValue, excluded_keys: Set[str] | None = None
) -> Iterable[str]:
    """Yields leaf device names under a node.

    A leaf device is represented by:
      - A dict entry with value None: {"Asus ROG Phone 6": None}
      - A string inside a list: {"Some Series": ["Model A", "Model B"]}
      - Nested dicts are traversed recursively.
    """
    excluded = excluded_keys or set()

    def from_dict(d: Dict[str, JsonValue]) -> Iterable[str]:
        for k, v in d.items():
            if _is_metadata_key(k) or k in excluded:
                continue
            if v is None:
                yield k
            elif isinstance(v, dict):
                yield from from_dict(v)
            elif isinstance(v, list):
                yield from from_list(v, parent_key=k)

    def from_list(items: List[JsonValue], parent_key: Optional[str] = None) -> Iterable[str]:
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
    exclude_map: Dict[str, Set[str]] | None = None,
) -> Dict[str, List[str]]:
    """Find target categories in the tree and collect leaf devices under them."""
    targets: Set[str] = set(target_categories)
    out: Dict[str, List[str]] = {t: [] for t in targets}
    excludes = exclude_map or {}

    def handle_match(cat: str, value: JsonValue) -> None:
        excluded = excludes.get(cat, set())
        leaves = list(_collect_leaf_device_names(value, excluded_keys=excluded))
        if value is None:
            leaves.append(cat)
        out[cat].extend(leaves)

    def dfs(current: JsonValue) -> None:
        if isinstance(current, dict):
            for k, v in current.items():
                if _is_metadata_key(k):
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

    for category in out:
        seen: Set[str] = set()
        unique_ordered = [x for x in out[category] if not (x in seen or seen.add(x))]
        out[category] = sorted(unique_ordered)

    return out


def collect_child_devices(
    data: Dict[str, JsonValue],
    target_categories: List[str],
    parent: str = "root",
    depth: int = 0,
    exclude_subtrees: Dict[str, Iterable[str]] | None = None,
) -> Dict[str, List[str]]:
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
    categories: List[str],
    exclude_subtrees: Dict[str, Iterable[str]] | None = None,
) -> Dict[str, List[str]]:
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
            logger.error("Failed to fetch category: %s", e, exc_info=True)
            data = {}

    logger.info("Collecting child devices in memory...")
    child_devices = collect_child_devices(data, categories, exclude_subtrees=exclude_subtrees)

    for category, devices in child_devices.items():
        print(f"\nChild devices for {category}:")
        if devices:
            print(json.dumps(devices, indent=2, ensure_ascii=False))
        else:
            print(f"No child devices found for {category}")
    print(_to_ifixit_title('nokia 3.1plus'))
    print(_to_ifixit_title('Super Nintendo Entertainment System (SNS-101)'))
    return child_devices


def _to_ifixit_title(name: str) -> str:
    """Converts a human-readable device name into a baseline iFixit wiki title.

    Args:
        name: Human-readable device name (e.g., 'Samsung Galaxy S22 Ultra').

    Returns:
        A baseline iFixit title format (e.g., 'Samsung_Galaxy_S22_Ultra').
    """
    s = re.sub(r"\s+", "_", name.strip())
    s = re.sub(r"[^A-Za-z0-9_().\-]+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = re.sub(r"\(", "%28", s)
    s = re.sub(r"\)", "%29", s)
    return s


def _normalize_key(s: str) -> str:
    """Normalized key for robust matching between categories/devices and guide groups."""
    return _to_ifixit_title(s).lower()


def fetch_teardown_guides(client: IFixitAPIClient) -> Dict[str, List[Dict[str, object]]]:
    """Fetch all teardown guides grouped by category.

    Retrieves guides with pagination and groups them by category. Each guide keeps its
    title, url, and derived tags from iFixit flags. Dedupe is performed later by (title, url).

    Args:
        client: The IFixitAPIClient instance.

    Returns:
        A dictionary mapping normalized categories to a list of guide dicts:
        {'title': str, 'url': str, 'tags': List[str]}.
    """
    params = {"filter": "teardown", "limit": 200}
    results: Dict[str, List[Dict[str, object]]] = {}
    lock = __import__("threading").Lock()
    offset = 0
    max_workers = 8
    batch_size = 200

    def is_main_teardown(category: str, title: str) -> bool:
        """Check if the guide title matches '<category> Teardown' pattern."""
        normalized_category = _to_ifixit_title(category).lower()
        normalized_title = _to_ifixit_title(title).lower()
        expected_title = f"{normalized_category}_teardown"
        return normalized_title == expected_title

    def fetch_page(page_offset: int) -> Dict[str, List[Dict[str, object]]]:
        """Fetch a single page of guides for the given offset."""
        try:
            page_params = params.copy()
            page_params["offset"] = page_offset
            guides = client.get_guides(params=page_params)
            page_results: Dict[str, List[Dict[str, object]]] = {}
            for guide in guides:
                if (
                    guide.get("url") is None
                    or guide.get("category") is None
                    or guide.get("title") is None
                ):
                    continue
                category = guide["category"]
                raw_flags = guide.get("flags", []) or []

                # Build tags from flags (lowercase, stable set).
                tags: List[str] = []
                if "GUIDE_ARCHIVED" in raw_flags:
                    tags.append("archived")
                if "GUIDE_STARRED" in raw_flags:
                    tags.append("starred")
                if "GUIDE_USER_CONTRIBUTED" in raw_flags:
                    tags.append("user_contributed")

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
        except Exception as e:
            logger.error("Failed to fetch offset %d: %s", page_offset, e)
            return {}

    def extend_map(dst: Dict[str, List[Dict[str, object]]], src: Dict[str, List[Dict[str, object]]]) -> None:
        for category, guides in src.items():
            if category not in dst:
                dst[category] = []
            dst[category].extend(guides)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            offsets = list(range(offset, offset + batch_size * max_workers, batch_size))
            futures = {executor.submit(fetch_page, off): off for off in offsets}
            page_results: Dict[str, List[Dict[str, object]]] = {}

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

    def _tag_priority(tags: List[str]) -> int:
        """Return priority rank based on tags: starred < user_contributed < others."""
        if "starred" in tags:
            return 0
        if "user_contributed" in tags:
            return 1
        return 2

    def sort_guides_for_category(category: str, guides: List[Dict[str, object]]) -> List[Dict[str, object]]:
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
        seen: Set[Tuple[str, str]] = set()
        unique: List[Dict[str, object]] = []
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

        def key_fn(g: Dict[str, object]) -> Tuple[int, int, int, str, str]:
            title = str(g["title"])
            url = str(g["url"])
            tags = list(g.get("tags", []))
            archived_bucket = 1 if "archived" in tags else 0  # archived last
            # Main bucket only matters for non-archived.
            main_bucket = 1
            if archived_bucket == 0 and is_main_teardown(category, title):
                main_bucket = 0
            tag_rank = _tag_priority(tags) if archived_bucket == 0 else 2
            return archived_bucket, main_bucket, tag_rank, title.lower(), url

        unique.sort(key=key_fn)
        return unique

    # Sort guides for each category.
    for category in list(results.keys()):
        results[category] = sort_guides_for_category(category, results[category])

    # Build normalized lookup to make matching resilient.
    normalized_results: Dict[str, List[Dict[str, object]]] = {
        _normalize_key(category): guides for category, guides in results.items()
    }

    logger.info("Fetched %d categories with teardown guides", len(results))
    return normalized_results


def print_device_data(
    client: IFixitAPIClient,
    devices: List[str],
    output_file: Optional[str] = None,
) -> None:
    """Fetches and prints device repairability scores and guide URLs concurrently."""
    logger.info("Fetching teardown guides for matching...")
    teardown_guides = fetch_teardown_guides(client)

    def dedupe(seq: List[str]) -> List[str]:
        seen: Set[str] = set()
        return [d for d in seq if not (d in seen or seen.add(d))]

    unique_devices = dedupe(devices)
    if not unique_devices:
        print("No devices provided.")
        return

    class _RateLimiter:
        """Token-bucket rate limiter for controlling API request rate."""

        def __init__(self, rate_per_sec: int, burst: Optional[int] = None) -> None:
            self.rate = max(1, rate_per_sec)
            self.capacity = burst if burst is not None else self.rate
            self._tokens: float = float(self.capacity)
            self._last: float = perf_counter()
            self._lock = __import__("threading").Lock()

        def acquire(self) -> None:
            wait_time = 0.0
            with self._lock:
                now = perf_counter()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens < 1.0:
                    wait_time = (1.0 - self._tokens) / self.rate
                else:
                    self._tokens -= 1.0
                    return
            if wait_time > 0.0:
                time.sleep(wait_time)
            with self._lock:
                now = perf_counter()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._tokens -= 1.0

    def _fetch_score(
        device_name: str, max_retries: int = 3, base_backoff: float = 0.75
    ) -> Tuple[str, str, Optional[float], Optional[str], Optional[str], Optional[str]]:
        ifixit_title = _to_ifixit_title(device_name)
        for attempt in range(max_retries):
            try:
                limiter.acquire()
                data = client.get_category(device_name=ifixit_title, params=None)
                repairability_score = data.get("repairability_score")
                manufacturer = next(
                    (
                        entry.get("value")
                        for entry in data.get("info", [])
                        if entry.get("name") == "Device Brand"
                    ),
                    None,
                )

                repair_link = f"https://www.ifixit.com/Device/{ifixit_title}"
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
                status_code = getattr(response, "status_code", None) if response else None
                retry_after = (
                    getattr(response, "headers", {}).get("Retry-After")
                    if response
                    else None
                )
                sleep_s = float(retry_after) if retry_after else base_backoff * (2 ** attempt)
                if status_code in {429, 500, 502, 503, 504} and attempt < max_retries - 1:
                    time.sleep(sleep_s)
                    continue
                if status_code == 404:
                    return device_name, ifixit_title, None, None, None, str(e)
                logger.error(
                    "Failed to fetch repairability score",
                    exc_info=e,
                    extra={"device": device_name},
                )
                return device_name, ifixit_title, None, None, None, str(e)
        return device_name, ifixit_title, None, None, None, "Max retries exceeded"

    def partition_results(
        rows: List[Tuple[str, str, Optional[float], Optional[str], Optional[str], Optional[str]]]
    ) -> Tuple[List[Tuple[str, str, Optional[float], Optional[str], Optional[str]]], List[Tuple[str, str]]]:
        with_score = [
            (n, t, s, brand, link_)
            for n, t, s, brand, link_, err in rows
            if s is not None
        ]
        without_score = [(n, t) for n, t, s, _brand, _link, err in rows if s is None]
        with_score.sort(key=lambda x: x[0])
        return with_score, without_score

    max_workers = 8
    requests_per_second = 4
    limiter = _RateLimiter(rate_per_sec=requests_per_second)

    results: List[Tuple[str, str, Optional[float], Optional[str], Optional[str], Optional[str]]] = []
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

    def print_outputs() -> None:
        if without_score:
            print("\nDevices without a repairability score (or failed to fetch):")
            for name, title in sorted(without_score, key=lambda x: x[0]):
                print(f"- {name} ({title})")
        print("\nRepairability scores for devices:")
        for name, title, score, _brand, _link in with_score:
            teardown_items = teardown_guides.get(_normalize_key(name), [])
            if teardown_items:
                # Include tags for visibility in console output.
                titles_and_urls = [
                    f"{g['title']} ({', '.join(g.get('tags', []))}) : {g['url']}"
                    for g in teardown_items
                ]
                print(f"- {name} ({title}): {score}, Teardown URLs: {titles_and_urls}")
            else:
                print(f"- {name} ({title}): {score}, No teardown URLs found")
        print("\nSummary:")
        print(f"- Devices with a repairability score: {len(with_score)}")
        print(f"- Total devices processed: {len(results)}")
        matched = sum(1 for name, _t, _s, _b, _l in with_score if _normalize_key(name) in teardown_guides)
        print(f"- Devices with matched teardown URLs: {matched}")

    print_outputs()

    if output_file:
        try:
            # Build payload including devices with and without a repairability score
            # Start with all devices that returned data (including those with score=None)
            all_entries = [
                {
                    "name": name,
                    "title": title,
                    "repairability_score": score,
                    "brand": brand,
                    "link": links,
                    "teardown_urls": [
                        {
                            "title": guide["title"],
                            "url": guide["url"],
                            "tags": guide.get("tags", []),
                            "difficulty": guide.get("difficulty"),
                        }
                        for guide in teardown_guides.get(_normalize_key(name), [])
                    ],
                }
                for name, title, score, brand, links, _err in results
            ]
            # Also include devices that failed (e.g., 404) so they appear as well
            # without duplicating already present entries from results list above.
            existing_keys = {(e[0], e[1]) for e in results}
            all_entries.extend(
                {
                    "name": name,
                    "title": title,
                    "repairability_score": None,
                    "brand": None,
                    "link": None,
                    "teardown_urls": [
                        {
                            "title": guide["title"],
                            "url": guide["url"],
                            "tags": guide.get("tags", []),
                            "difficulty": guide.get("difficulty"),
                        }
                        for guide in teardown_guides.get(_normalize_key(name), [])
                    ],
                }
                for name, title in without_score
                if (name, title) not in existing_keys
            )

            # Sort and write
            all_entries.sort(key=lambda d: ((d.get("brand") or ""), d["name"], d["title"]))
            write_json_atomic(output_file, all_entries)
            logger.info("Wrote %d devices (including those without scores) to: %s", len(all_entries), output_file)
        except Exception as e:
            logger.error("Failed to write results to %s: %s", output_file, e, exc_info=True)
            raise


def main() -> None:
    """Entry point for the script.

    Builds the devices_with_scores.json from iFixit data using in-memory category traversal.
    """
    parser = argparse.ArgumentParser(
        description="Fetch iFixit device data"
    )
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
    args = parser.parse_args()

    client = IFixitAPIClient(log_level=log_level, proxy=True, raise_for_status=False)
    exclude_subtrees = {"iPhone": {"iPhone Accessories"}}

    # Fetch child devices in memory
    child_map = get_child_devices_for_categories(client, args.categories, exclude_subtrees)

    # Build the device list from selected categories
    demo_devices = []
    for cat in args.categories:
        demo_devices.extend(child_map.get(cat, []))

    demo_devices = list(dict.fromkeys(demo_devices))
    if demo_devices:
        print_device_data(client, demo_devices, args.scores_output)
    else:
        print("No demo devices found.")


if __name__ == "__main__":
    main()
