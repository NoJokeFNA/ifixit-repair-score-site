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

    def compare(label, old, new):
        lost = sorted(old - new)
        report["metrics"][label] = {"previous": len(old), "candidate": len(new), "lost": len(lost)}
        report["losses"][label] = lost
        if lost:
            message = f"{label}: {len(lost)} of {len(old)} previously published entries disappeared"
            if len(lost) >= max(1, math.ceil(len(old) * MAX_LOSS_RATIO)):
                report["errors"].append(message)
            else:
                report["warnings"].append(message)

    if not sources or not devices:
        report["errors"].append("Candidate source and device snapshots must not be empty")
    source_ids = [row.get("source_url") for row in sources]
    device_ids = [row.get("name") for row in devices]
    if any(not isinstance(value, str) or not value for value in source_ids + device_ids):
        report["errors"].append("Candidate entries require nonempty source URLs and device names")
    if len(set(source_ids)) != len(source_ids) or len(set(device_ids)) != len(device_ids):
        report["errors"].append("Candidate snapshots contain duplicate identities")
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
    compare("devices", before_devices, set(device_ids))
    compare(
        "french_scores",
        before_scored,
        {row["name"] for row in devices if row.get("france_repairability_score") is not None},
    )
    compare(
        "ifixit_scores", before_ifixit, {row["name"] for row in devices if row.get("repairability_score") is not None}
    )

    def identified(rows):
        return {row["name"] for row in rows or [] if (row.get("model_identification") or {}).get("model_numbers")}

    def variant_ids(rows):
        return {
            f"{row['name']} :: {variant.get('variant_id') or variant['name']}"
            for row in rows or []
            for variant in (row.get("model_identification") or {}).get("variants", [])
            if variant.get("name")
        }

    compare("model_identifications", identified(previous_devices), identified(devices))
    compare("regional_variants", variant_ids(previous_devices), variant_ids(devices))
    by_name = {row["name"]: row for row in devices}
    for previous in previous_devices or []:
        old = variant_ids([previous])
        current = by_name.get(previous["name"])
        lost = old - variant_ids([current] if current else [])
        if len(old) >= 3 and len(lost) >= math.ceil(len(old) * 0.5):
            report["errors"].append(f"{previous['name']}: {len(lost)} of {len(old)} named variants disappeared")
    if previous_sources and not before_sources:
        report["errors"].append("Previous source snapshot lacks stable source URLs; establish a reviewed baseline")
    # A small manufacturer outage must not disappear inside a large global total.
    old_brands, new_brands = defaultdict(set), defaultdict(set)
    for row in previous_devices or []:
        if row.get("brand") and row.get("france_repairability_score") is not None:
            old_brands[row["brand"]].add(row["name"])
    for row in devices:
        if row.get("brand") and row.get("france_repairability_score") is not None:
            new_brands[row["brand"]].add(row["name"])
    for brand, old in old_brands.items():
        lost = old - new_brands[brand]
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
