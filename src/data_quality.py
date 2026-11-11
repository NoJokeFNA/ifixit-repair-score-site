"""Compare candidate imports with the last published data before any replacement."""

import argparse
import json
import math
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path


class DataQualityError(RuntimeError):
    pass


MAX_LOSS_RATIO = 0.10


def read_snapshot(path: str | Path) -> list[dict] | None:
    target = Path(path)
    if not target.exists():
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise DataQualityError(f"Invalid previous snapshot: {target.name}")
    return data


def compare_snapshots(previous_sources, sources, previous_devices, devices) -> dict:
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "passed",
        "errors": [],
        "warnings": [],
        "metrics": {},
        "losses": {},
    }

    def compare(label, old, new, confirmed_removals=None):
        lost = sorted(old - new)
        report["metrics"][label] = {"previous": len(old), "candidate": len(new), "lost": len(lost)}
        report["losses"][label] = lost
        if lost:
            message = f"{label}: {len(lost)} of {len(old)} previously published entries disappeared"
            confirmed = set(lost) & (confirmed_removals or set())
            if confirmed:
                message += f" ({len(confirmed)} confirmed source removals)"
            if len(set(lost) - confirmed) >= max(1, math.ceil(len(old) * MAX_LOSS_RATIO)):
                report["errors"].append(message)
            else:
                report["warnings"].append(message)

    removed = [row for row in devices if row.get("source_status") == "not_found"]
    report["source_removals"] = [{"name": row["name"], "source_url": row.get("source_url")} for row in removed]
    removed_names = {row["name"] for row in removed}
    report["warnings"].extend(f"{row['name']}: confirmed HTTP 404; removed from published devices" for row in removed)
    devices = [row for row in devices if row.get("source_status") != "not_found"]
    if not sources or not devices:
        report["errors"].append("Candidate source and device snapshots must not be empty")
    source_ids = [row.get("source_url") for row in sources]
    device_ids = [row.get("name") for row in devices]
    if any(not isinstance(value, str) or not value for value in source_ids + device_ids):
        report["errors"].append("Candidate entries require nonempty source URLs and device names")
    if len(set(source_ids)) != len(source_ids) or len(set(device_ids)) != len(device_ids):
        report["errors"].append("Candidate snapshots contain duplicate identities")
    previous_by_name = {row["name"]: row for row in previous_devices or []}
    previous_by_id = {row["wikiid"]: row for row in previous_devices or [] if row.get("wikiid") is not None}

    def model_identity(row):
        identity = row.get("model_identification") or {}
        numbers = identity.get("model_numbers") or []
        brand = row.get("brand") or identity.get("brand")
        if (
            not isinstance(brand, str)
            or not brand.strip()
            or not isinstance(numbers, list)
            or not numbers
            or not all(isinstance(number, str) and number for number in numbers)
            or not identity.get("reference_urls")
        ):
            return None
        return brand.strip().casefold(), tuple(sorted(set(numbers)))

    previous_models = defaultdict(list)
    for row in previous_devices or []:
        if model_identity(row):
            previous_models[model_identity(row)].append(row)
    candidate_models = Counter(model_identity(row) for row in devices if model_identity(row))
    candidate_keys = {}
    report["renames"] = []
    for row in devices:
        if row.get("import_error"):
            report["errors"].append(row["import_error"])
        previous = previous_by_id.get(row.get("wikiid"))
        matched_by = "wikiid"
        aliases = [name for name in row.get("previous_names", []) if name in previous_by_name]
        if len(aliases) > 1:
            report["errors"].append(f"Ambiguous previous device names: {row['name']}")
        if previous is None and len(aliases) == 1:
            previous = previous_by_name[aliases[0]]
            matched_by = "redirect"
        elif previous is not None and aliases and previous["name"] not in aliases:
            report["errors"].append(f"Wiki ID and redirect disagree about previous device: {row['name']}")
        model = model_identity(row)
        if (
            previous is None
            and row["name"] not in previous_by_name
            and row.get("source_status") == "verified"
            and not row.get("import_error")
            and model
            and len(previous_models[model]) == 1
            and candidate_models[model] == 1
            and previous_models[model][0]["name"] not in device_ids
        ):
            previous = previous_models[model][0]
            matched_by = "model_numbers"
        same_name = previous_by_name.get(row["name"])
        if (
            same_name
            and same_name.get("wikiid") is not None
            and row.get("wikiid") is not None
            and same_name["wikiid"] != row["wikiid"]
            and not any(link.get("wikiid") == same_name["wikiid"] for link in row.get("redirects", []))
        ):
            if (
                row.get("source_status") == "verified"
                and model
                and model_identity(same_name) == model
                and len(previous_models[model]) == candidate_models[model] == 1
            ):
                report["warnings"].append(f"Wiki ID changed; complete model-number identity verified: {row['name']}")
            else:
                report["errors"].append(f"Wiki ID changed without a verified redirect or model identity: {row['name']}")
        key = previous["name"] if previous else row["name"]
        candidate_keys[row["name"]] = key
        if key != row["name"]:
            if row["name"] in previous_by_name:
                report["errors"].append(f"Device rename collides with existing device: {row['name']}")
            report["renames"].append(
                {
                    "previous": key,
                    "candidate": row["name"],
                    "wikiid": row.get("wikiid"),
                    "matched_by": matched_by,
                }
            )
    wiki_ids = [row["wikiid"] for row in devices if row.get("wikiid") is not None]
    if len(set(wiki_ids)) != len(wiki_ids) or len(set(candidate_keys.values())) != len(devices):
        report["errors"].append("Candidate snapshots contain duplicate resolved device identities")

    def device_key(row):
        return candidate_keys[row["name"]]

    for row in sources:
        value = row.get("repairability_score")
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0 <= value <= 10
        ):
            report["errors"].append(f"Invalid French source score: {row.get('name')}")
            break
    for row in devices:
        for field in ["repairability_score", "france_repairability_score"]:
            value = row.get(field)
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0 <= value <= 10
            ):
                report["errors"].append(f"Invalid {field}: {row.get('name')}")
    before_sources = {row.get("source_url") for row in previous_sources or [] if row.get("source_url")}
    before_devices = {row["name"] for row in previous_devices or []}
    before_scored = {row["name"] for row in previous_devices or [] if row.get("france_repairability_score") is not None}
    before_ifixit = {row["name"] for row in previous_devices or [] if row.get("repairability_score") is not None}
    compare("source_products", before_sources, set(source_ids))
    compare("devices", before_devices, {device_key(row) for row in devices}, removed_names)
    compare(
        "french_scores",
        before_scored,
        {device_key(row) for row in devices if row.get("france_repairability_score") is not None},
        removed_names,
    )
    compare(
        "ifixit_scores",
        before_ifixit,
        {device_key(row) for row in devices if row.get("repairability_score") is not None},
        removed_names,
    )

    def identified(rows, key):
        return {key(row) for row in rows or [] if (row.get("model_identification") or {}).get("model_numbers")}

    def variant_ids(rows, key=lambda row: row["name"]):
        return {
            f"{key(row)} :: {variant.get('variant_id') or variant['name']}"
            for row in rows or []
            for variant in (row.get("model_identification") or {}).get("variants", [])
            if variant.get("name")
        }

    by_name = {device_key(row): row for row in devices}
    verified_variant_changes = {
        key
        for key, row in by_name.items()
        if row.get("source_status") == "verified"
        and not row.get("import_error")
        and (
            (row.get("model_identification") or {}).get("variant_status") in {"available", "empty"}
            or (row.get("wiki_namespace") == "WIKI" and row.get("redirects"))
        )
    }
    confirmed = removed_names | verified_variant_changes
    compare(
        "model_identifications",
        identified(previous_devices, lambda row: row["name"]),
        identified(devices, device_key),
        removed_names | {key for key in verified_variant_changes if by_name[key].get("wiki_namespace") == "WIKI"},
    )
    confirmed_variants = variant_ids([row for row in previous_devices or [] if row["name"] in confirmed])
    compare("regional_variants", variant_ids(previous_devices), variant_ids(devices, device_key), confirmed_variants)
    for previous in previous_devices or []:
        old = variant_ids([previous])
        current = by_name.get(previous["name"])
        lost = old - variant_ids([current] if current else [], device_key)
        if len(old) >= 3 and len(lost) >= math.ceil(len(old) * 0.5):
            detail = ""
            if current and current.get("wiki_namespace") == "WIKI":
                detail = f"; redirected to WIKI/{current['title']}, which has no category variants endpoint"
            category = "warnings" if previous["name"] in confirmed else "errors"
            report[category].append(f"{previous['name']}: {len(lost)} of {len(old)} named variants disappeared{detail}")
    if previous_sources and not before_sources:
        report["errors"].append("Previous source snapshot lacks stable source URLs; establish a reviewed baseline")
    # A small manufacturer outage must not disappear inside a large global total.
    old_brands, new_brands = defaultdict(set), defaultdict(set)
    for row in previous_devices or []:
        if row.get("brand") and row.get("france_repairability_score") is not None:
            old_brands[row["brand"]].add(row["name"])
    for row in devices:
        if row.get("brand") and row.get("france_repairability_score") is not None:
            new_brands[row["brand"]].add(device_key(row))
    for brand, old in old_brands.items():
        lost = old - new_brands[brand] - removed_names
        if len(old) >= 3 and len(lost) >= math.ceil(len(old) * 0.5):
            report["errors"].append(f"{brand}: {len(lost)} of {len(old)} French scores disappeared")
    report["match_statuses"] = dict(
        Counter(row.get("france_repairability", {}).get("status", "unverified") for row in devices)
    )
    report["baseline_available"] = previous_sources is not None and previous_devices is not None
    report["status"] = "blocked" if report["errors"] else "warning" if report["warnings"] else "passed"
    return report


def write_report(path: str | Path, report: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def summarize(report: dict) -> str:
    lines = [
        f"## Import quality: {report['status']}",
        "",
        "| Metric | Previous | Candidate | Lost |",
        "|---|---:|---:|---:|",
    ]
    for key, values in report.get("metrics", {}).items():
        lines.append(f"| {key} | {values['previous']} | {values['candidate']} | {values['lost']} |")
    if report.get("api"):
        api = report["api"]
        lines += [
            "",
            (
                f"API requests: {api['requests']}; configured ceiling: {api['rate_limit']}/s; "
                f"current rate: {api['current_rate']}/s; throttling responses: {api['throttles']}."
            ),
        ]
    if report.get("renames"):
        lines += ["", "### Verified renames"]
        lines.extend(
            f"- {row['previous']} → {row['candidate']} (wikiid: {row['wikiid']}; "
            f"matched by {row.get('matched_by', 'source identity')})"
            for row in report["renames"]
        )
    if report.get("source_removals"):
        lines += ["", "### Source removals (HTTP 404)"]
        lines.extend(f"- {row['name']}: {row['source_url']}" for row in report["source_removals"])
    for label in ["errors", "warnings"]:
        if report.get(label):
            lines += ["", f"### {label.capitalize()}"]
            lines.extend(f"- {message}" for message in report[label])
    lines += ["", "Published data is retained when an import is blocked."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize", required=True)
    args = parser.parse_args()
    target = Path(args.summarize)
    report = (
        json.loads(target.read_text())
        if target.exists()
        else {"status": "blocked", "errors": ["Import stopped before data comparison; see job logs."]}
    )
    summary = summarize(report)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as output:
            output.write(summary)
    else:
        print(summary)
