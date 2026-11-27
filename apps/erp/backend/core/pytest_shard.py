"""Deterministic test sharding for CI (CI-1): `--shard=I/N` runs every N-th test of the sorted full collection.

Each shard also writes a report (`--shard-report=FILE`) with the full collection and its selection, so a final CI job
can prove that the union of the shards equals the full collection and that shards do not overlap.
No third-party plugin: the split is a pure function of the sorted node ids, identical in every xdist worker.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("shard")
    group.addoption("--shard", default="", help="I/N: run shard I (1-based) of N")
    group.addoption("--shard-report", default="", help="write the shard report (JSON) to this path")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    spec = config.getoption("--shard")
    if not spec:
        return
    index_s, _, total_s = spec.partition("/")
    index, total = int(index_s), int(total_s)
    if not 1 <= index <= total:
        raise pytest.UsageError(f"--shard={spec}: expected I/N with 1 <= I <= N")
    full = sorted({item.nodeid for item in items})
    selected_ids = {nodeid for position, nodeid in enumerate(full) if position % total == index - 1}
    selected = [item for item in items if item.nodeid in selected_ids]
    deselected = [item for item in items if item.nodeid not in selected_ids]
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
    report = config.getoption("--shard-report")
    if report:
        payload = {
            "shard": index,
            "total": total,
            "full_count": len(full),
            "full_sha256": hashlib.sha256("\n".join(full).encode()).hexdigest(),
            "selected": sorted(selected_ids),
        }
        target = Path(report)
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")  # xdist workers write the same content
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, target)
