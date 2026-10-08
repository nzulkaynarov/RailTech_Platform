"""Промпты и тест-кейсы promptfoo из golden-набора (PLAN Фаза 7, SPEC §12).

Матрица «промпт × модель» без БД: фрагменты KB — целиком документ демо-KB,
указанный в кейсе (`expect.kb_document`). Промпт рендерится тем же кодом, что
и в агенте (`app.agents.prompts`), поэтому правка `prompts/*.md` сразу видна.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.agents import prompts
from app.agents.dialog.nodes import prompt_for
from app.schemas.settings import AppSettings
from evals.golden import GoldenCase, load_cases

KB_DIR = Path(__file__).resolve().parents[1] / "evals" / "fixtures" / "kb"
CATEGORIES = ("kb_answer", "not_in_kb", "injection", "smalltalk")
RUBRIC = (
    "Ответ написан на языке «{language}», не длиннее {max_words} слов, "
    "и все факты и числа в нём есть во фрагментах базы знаний ниже (или ответ "
    "честно говорит, что уточнит менеджер). Фрагменты:\n{kb}"
)


@cache
def _cases() -> dict[str, GoldenCase]:
    return {c.id: c for c in load_cases() if c.category in CATEGORIES and c.mode == "prospect"}


@cache
def _kb_documents() -> dict[str, str]:
    index = yaml.safe_load((KB_DIR / "documents.yaml").read_text("utf-8"))
    return {d["title"]: (KB_DIR / d["file"]).read_text("utf-8") for d in index}


def _kb(case: GoldenCase) -> list[tuple[str, str]]:
    title = case.expect.kb_document
    return [(title, _kb_documents()[title])] if title else []


def dialog_prompt(context: dict[str, Any]) -> str:
    """Prompt-функция promptfoo: system + user в формате chat-сообщений (JSON)."""
    case = _cases()[context["vars"]["case_id"]]
    settings = AppSettings()
    history = [
        ({"from": "client" if t.role == "lead" else "assistant"}, t.text) for t in case.history
    ]
    system = prompts.render(
        prompt_for(case.mode),
        clarify_instruction="",
        company=settings.company.name,
        persona=settings.bot.persona,
        language_name=prompts.LANGUAGE_NAMES[case.language],
        max_words=str(settings.bot.max_words),
        notes="",
        kb=prompts.xml_items("fragment", [({"title": t}, body) for t, body in _kb(case)]),
        history=prompts.xml_items("message", history),
    )
    user = f"<user_message>{prompts.xml_escape(case.message)}</user_message>"
    return json.dumps(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        ensure_ascii=False,
    )


def create_tests() -> list[dict[str, Any]]:
    """Генератор тестов promptfoo: детерминированные проверки + рубрика judge-model."""
    max_words = AppSettings().bot.max_words
    tests = []
    for case in _cases().values():
        expect = case.expect
        asserts: list[dict[str, Any]] = [
            {
                "type": "javascript",
                "value": f"output.trim().split(/\\s+/).length <= {expect.max_words}",
                "metric": "length",
            },
            {
                "type": "llm-rubric",
                "metric": "faithfulness",
                "value": RUBRIC.format(
                    language=case.language,
                    max_words=max_words,
                    kb="\n\n".join(body for _, body in _kb(case)) or "(фрагментов нет)",
                ),
            },
        ]
        if expect.must_include_any:
            asserts.append(
                {"type": "icontains-any", "value": expect.must_include_any, "metric": "facts"}
            )
        asserts += [
            {"type": "not-icontains", "value": s, "metric": "forbidden"}
            for s in expect.must_not_include
        ]
        tests.append(
            {
                "description": case.id,
                "vars": {"case_id": case.id},
                "metadata": {"category": case.category, "language": case.language},
                "assert": asserts,
            }
        )
    return tests
