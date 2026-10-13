"""`python -m app kb-eval` — проверка поиска на демо-KB (гейт PLAN Фазы 1, ADR-0007).

Печатает попадание ожидаемого документа в top-3 по каждому вопросу и
распределение косинусной близости для вопросов «в KB» и «вне KB» — по нему
калибруется `kb.min_score`. Код выхода 1, если гейт не пройден.
"""

import asyncio
import statistics
from pathlib import Path
from typing import Any

import yaml

from app.container import get_container
from app.services.kb.search import KbSearchService

DEFAULT_FILE = Path("evals/fixtures/kb/search_questions.yaml")
GATE_TOTAL = 13
GATE_UZ = 3


async def run(path: Path = DEFAULT_FILE) -> int:
    data: dict[str, Any] = await asyncio.to_thread(
        lambda: yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    container = get_container()
    service = KbSearchService(container.session_factory, container.embedder)
    passed, uz_passed, in_scores = 0, 0, []
    for item in data["questions"]:
        result = await service.search(item["q"], language=item["lang"])
        titles = [h.document_title for h in result.hits[:3]]
        ok = item["expected"] in titles
        passed += ok
        uz_passed += ok and item["lang"] == "uz"
        in_scores.append(result.best_score or 0.0)
        mark = "✔" if ok else "✖"
        score = result.best_score or 0
        print(f"{mark} [{item['lang']}] {item['q']}  best={score:.3f}")  # noqa: T201
    out_scores = []
    for item in data.get("out_of_kb", []):
        result = await service.search(item["q"], language=item["lang"])
        out_scores.append(result.best_score or 0.0)
        print(f"· [вне KB] {item['q']}  best={result.best_score or 0:.3f}")  # noqa: T201
    _report(passed, uz_passed, len(data["questions"]), in_scores, out_scores)
    await container.engine.dispose()
    return 0 if passed >= GATE_TOTAL and uz_passed >= GATE_UZ else 1


def _report(passed: int, uz: int, total: int, inside: list[float], outside: list[float]) -> None:
    print(f"\ntop-3: {passed}/{total} (гейт ≥ {GATE_TOTAL}), uz: {uz} (гейт ≥ {GATE_UZ})")  # noqa: T201
    if inside and outside:
        print(  # noqa: T201
            f"близость: в KB min={min(inside):.3f} median={statistics.median(inside):.3f}; "
            f"вне KB max={max(outside):.3f} — порог kb.min_score между ними"
        )
