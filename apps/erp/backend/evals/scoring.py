"""Офлайн-оценка ответов ИИ против golden-кейсов. Чистые функции без I/O и без моделей.

Разбор запроса: каждой ожидаемой строке ищется своя строка ответа (ключевое слово имени,
без учёта регистра и в `name`, и в `name_canonical`); совпало количество и единица — строка
засчитана; лишние строки сверх `max_extra_lines` — провал («модель выдумала позицию»).
Сопоставление: лучший кандидат строки == ожидаемому; `null` в ожидании — у строки не должно
быть кандидатов (уверенно неверный ответ хуже пустого).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cases import ExpectedLine, IntakeCase, MatchCase

PASS_THRESHOLD = 1.0


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    checks: int
    passed_checks: int
    failures: tuple[str, ...] = field(default_factory=tuple)

    @property
    def score(self) -> float:
        return self.passed_checks / self.checks if self.checks else 1.0

    @property
    def passed(self) -> bool:
        return self.score >= PASS_THRESHOLD


def _norm(text: str) -> str:
    return " ".join(str(text or "").casefold().replace("ё", "е").split())


def _name_hits(expected: ExpectedLine, item: dict) -> bool:
    haystack = _norm(f"{item.get('name', '')} {item.get('name_canonical', '')}")
    return any(_norm(word) in haystack for word in expected.name_any)


def _line_failures(expected: ExpectedLine, item: dict) -> list[str]:
    failures = []
    if expected.quantity is not None and int(item.get("quantity") or 0) != expected.quantity:
        failures.append(f"{expected.name_any[0]}: quantity {item.get('quantity')} != {expected.quantity}")
    if expected.unit_any and not any(_norm(unit) in _norm(item.get("unit", "")) for unit in expected.unit_any):
        failures.append(f"{expected.name_any[0]}: unit {item.get('unit')!r} not in {list(expected.unit_any)}")
    return failures


def score_intake(case: IntakeCase, items: list[dict]) -> CaseScore:
    """Ответ разбора (строки после нормализации сервиса) против кейса."""
    remaining = list(items)
    failures: list[str] = []
    passed = 0
    for expected in case.lines:
        match = next((item for item in remaining if _name_hits(expected, item)), None)
        if match is None:
            failures.append(f"missing line {list(expected.name_any)}")
            continue
        remaining.remove(match)
        line_failures = _line_failures(expected, match)
        failures.extend(line_failures)
        passed += 0 if line_failures else 1
    checks = len(case.lines) + 1
    if len(remaining) > case.max_extra_lines:
        failures.append(f"{len(remaining)} unexpected extra line(s): {[item.get('name') for item in remaining]}")
    else:
        passed += 1
    return CaseScore(case.id, checks, passed, tuple(failures))


def score_match(case: MatchCase, ranked: list[dict]) -> CaseScore:
    """Ответ ранжирования (`rank_candidates`) против кейса: лучший кандидат каждой строки."""
    top_by_line = {row["line_index"]: (row.get("candidates") or [{}])[0].get("product_id") for row in ranked}
    failures = []
    passed = 0
    for index, line in enumerate(case.lines):
        got = top_by_line.get(index)
        if got == line.expect_product_id:
            passed += 1
        else:
            failures.append(f"line {index} {line.name!r}: top {got} != expected {line.expect_product_id}")
    return CaseScore(case.id, len(case.lines), passed, tuple(failures))


def summarize(scores: list[CaseScore]) -> dict:
    total = len(scores)
    passed = sum(1 for score in scores if score.passed)
    return {
        "cases": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "mean_score": round(sum(score.score for score in scores) / total, 3) if total else 0.0,
        "failed": {score.case_id: list(score.failures) for score in scores if not score.passed},
    }
