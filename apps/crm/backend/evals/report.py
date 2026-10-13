"""Отчёт evals: JSON в `evals/reports/` (для PR-комментария) и оценки в Langfuse."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import structlog

from app.integrations import langfuse as lf

logger = structlog.get_logger(__name__)

REPORT_DIR = Path(os.environ.get("EVAL_REPORT_DIR", Path(__file__).parent / "reports"))


def git_sha() -> str:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha[:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    return out.stdout.strip() or "unknown"


def write(name: str, payload: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{name}.json"
    path.write_text(
        json.dumps({"git_sha": git_sha(), **payload}, ensure_ascii=False, indent=2), "utf-8"
    )
    return path


def score(trace_id: str | None, name: str, value: float, comment: str | None = None) -> None:
    """Оценка на трейс хода в Langfuse (если Langfuse настроен)."""
    client = lf.client()
    if client is None or trace_id is None:
        return
    client.create_score(
        trace_id=trace_id, name=name, value=value, comment=comment, metadata={"git_sha": git_sha()}
    )


def dataset_run(dataset: str, case_id: str, case_input: Any, trace_id: str | None) -> None:
    """Кейс → элемент датасета Langfuse, ход → run `git-<sha>` (сравнение прогонов в UI)."""
    client = lf.client()
    if client is None or trace_id is None:
        return
    item_id = f"{dataset}:{case_id}"
    try:
        if dataset not in _DATASETS:
            client.create_dataset(name=dataset, description="RailTech golden (evals/)")
            _DATASETS.add(dataset)
        client.create_dataset_item(dataset_name=dataset, id=item_id, input=case_input)
        client.api.dataset_run_items.create(
            run_name=f"git-{git_sha()}", dataset_item_id=item_id, trace_id=trace_id
        )
    except Exception as exc:  # noqa: BLE001 — отчётность не должна валить eval
        logger.warning("langfuse_dataset_run_failed", case_id=case_id, error=type(exc).__name__)


_DATASETS: set[str] = set()
