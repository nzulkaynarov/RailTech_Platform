"""Советы по качеству строк запроса до отправки (feature `preflight`, алиас `intake-model`).

Расплывчатые наименования, неправдоподобное количество, сомнительная единица, дубли, нет
ключевой характеристики — это СОВЕТЫ, не блокировка. Каждый `line_index` обязан указывать на
переданную строку: модель предупреждена о диапазоне, а вне диапазона мы отбрасываем сами.
"""

from __future__ import annotations

from django.conf import settings

from .gateway import JsonCall, call_json, text_block
from .prompts import load_prompt

PREFLIGHT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_index": {
                        "type": "integer",
                        "description": "Индекс строки из ДАННЫХ (0-based). ТОЛЬКО из переданных строк.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warning"],
                        "description": "warning — стоит исправить; info — мелкое замечание",
                    },
                    "issue": {"type": "string", "description": "Что не так со строкой (кратко)"},
                    "suggestion": {"type": "string", "description": "Как улучшить (конкретно)"},
                },
                "required": ["line_index", "severity", "issue", "suggestion"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

#: Потолок совпадает с потолком эндпоинта — один вызов ограничен.
MAX_PREFLIGHT_LINES = 50


def format_lines(lines: list[dict]) -> str:
    """Пронумерованный блок строк для сообщения пользователя; индексы — единственно допустимые."""
    blocks = []
    for index, line in enumerate(lines):
        name = str(line.get("name") or "").strip() or "(без названия)"
        quantity = line.get("quantity")
        parts = [
            f"Строка {index}: {name}",
            f"кол-во={quantity if quantity not in (None, '') else '—'}",
            f"ед.={str(line.get('unit') or '').strip() or '—'}",
        ]
        for key, label, limit in (
            ("mpn", "артикул", None),
            ("gost_drawing", "ГОСТ/чертёж", None),
            ("note", "прим.", 200),
        ):
            value = str(line.get(key) or "").strip()
            if value:
                parts.append(f"{label}={value[:limit]}")
        blocks.append("; ".join(parts))
    return "\n".join(blocks)


def _clean_finding(finding: dict, valid_indices: set[int]) -> dict | None:
    line_index = finding.get("line_index")
    if line_index not in valid_indices:  # Rule 1: only GIVEN lines
        return None
    issue = str(finding.get("issue") or "").strip()[:300]
    if not issue:
        return None
    severity = str(finding.get("severity") or "warning").strip().lower()
    return {
        "line_index": line_index,
        "severity": severity if severity in ("info", "warning") else "warning",
        "issue": issue,
        "suggestion": str(finding.get("suggestion") or "").strip()[:300],
    }


def pre_flight_check(lines: list[dict], domain_code: str | None = None) -> list[dict]:
    """`[{line_index, severity, issue, suggestion}]`; [] при выключенном ИИ, без строк или ошибке."""
    if not getattr(settings, "AI_IMPORT_ENABLED", False) or not lines:
        return []
    bounded = lines[:MAX_PREFLIGHT_LINES]
    domain_hint = f" Предметная область заявки: {domain_code}." if domain_code else ""
    user_msg = f"Проверь {len(bounded)} строк заявки (индексы 0..{len(bounded) - 1}).{domain_hint}\n\n" + format_lines(
        bounded
    )
    prompt = load_prompt("preflight")
    result = call_json(
        JsonCall(
            feature="preflight",
            prompt=prompt,
            system=prompt.render(),
            user_content=[text_block(user_msg)],
            schema=PREFLIGHT_RESULT_SCHEMA,
            max_tokens=3000,
        )
    )
    if not result.ok:
        return []
    valid_indices = set(range(len(bounded)))
    cleaned = (_clean_finding(finding, valid_indices) for finding in result.data.get("findings", []) or [])
    return [finding for finding in cleaned if finding is not None]
