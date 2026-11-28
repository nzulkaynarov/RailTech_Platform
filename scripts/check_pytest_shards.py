#!/usr/bin/env python3
"""CI-1: the pytest shards of ERP must be disjoint and together equal the full collection.

Reads shard-report-<i>.json files written by apps/erp/backend/core/pytest_shard.py (--shard-report) and fails if
a shard is missing, shards saw different full collections, shards overlap, or the union is not the full collection.
Usage: check_pytest_shards.py <reports-dir> --shards N
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--shards", type=int, required=True)
    args = parser.parse_args()

    reports = {}
    for path in sorted(args.directory.glob("shard-report-*.json")):
        data = json.loads(path.read_text())
        reports[data["shard"]] = data
    errors = []
    missing = sorted(set(range(1, args.shards + 1)) - set(reports))
    if missing:
        errors.append(f"нет отчётов шардов: {missing}")
    if {(r["total"], r["full_count"], r["full_sha256"]) for r in reports.values()} != {
        (args.shards, next(iter(reports.values()))["full_count"], next(iter(reports.values()))["full_sha256"])
    } if reports else True:
        errors.append("шарды увидели разный полный набор тестов или разное число шардов")
    seen: dict[str, int] = {}
    for shard, report in sorted(reports.items()):
        for nodeid in report["selected"]:
            if nodeid in seen:
                errors.append(f"тест в двух шардах ({seen[nodeid]} и {shard}): {nodeid}")
            seen[nodeid] = shard
    if reports and not missing:
        full_count = next(iter(reports.values()))["full_count"]
        if len(seen) != full_count:
            errors.append(f"объединение шардов — {len(seen)} тестов, полный набор — {full_count}")
    for error in errors:
        print(f"::error::{error}")
    if errors:
        return 1
    print(f"ok: {args.shards} шардов, {len(seen)} тестов, пересечений нет, объединение = полный набор")
    return 0


if __name__ == "__main__":
    sys.exit(main())
