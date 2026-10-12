"""BOT-07: клиент просит документ, найдено несколько — выбор кнопками (без модели).

Id документов в кнопках — только из собственного поиска кода (docs-mcp по клиенту из подписанного
контекста, SPEC §1.5); принадлежность при нажатии проверяет `ClientBotService.document`.
"""

from typing import Any

import pytest

from app.agents.dialog.graph import DialogAgent
from app.agents.dialog.state import DialogResult
from app.domain.dialog_policy import Action
from app.schemas.settings import AppSettings
from tests.unit.agents.fakes import FakeTools, ReplayModel, kb, lead, reply

SETTINGS = AppSettings()


def doc(doc_id: int, title: str, day: str | None = None) -> dict[str, Any]:
    return {"document_id": doc_id, "title": title, "type": "invoice", "doc_date": day}


class DocTools(FakeTools):
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        super().__init__(lead(customer=True), kb(0.8))
        self.docs = docs

    async def call(self, server: str, tool: str, args: dict[str, Any], context: str) -> Any:
        if tool == "search_documents":
            self.calls.append((server, tool, args))
            return self.docs
        if tool == "get_document_link":
            self.calls.append((server, tool, args))
            return {"document_id": args["document_id"], "title": "Счёт №7", "url": "u"}
        return await super().call(server, tool, args, context)


async def run(tools: DocTools, model: ReplayModel, language: str = "ru") -> DialogResult:
    return await DialogAgent(tools, model).run(
        lead_id=1,
        text="Пришлите счёт",
        language=language,
        context_token="t",
        settings=SETTINGS,
        mode="customer",
    )


async def test_several_matches_offer_buttons_without_model() -> None:
    tools = DocTools([doc(7, "Счёт", "2026-09-01"), doc(9, "Счёт", "2026-10-01")])
    model = ReplayModel()
    result = await run(tools, model)
    assert result.action == Action.CHOOSE_DOCUMENT
    assert result.reply == SETTINGS.texts.docs_choose.ru
    assert result.document_choices == [(7, "Счёт · 2026-09-01"), (9, "Счёт · 2026-10-01")]
    assert model.requests == []


@pytest.mark.parametrize("language", ["uz", "en"])
async def test_choice_text_in_lead_language(language: str) -> None:
    tools = DocTools([doc(7, "Invoice"), doc(9, "Act")])
    result = await run(tools, ReplayModel(), language)
    assert result.reply == SETTINGS.texts.docs_choose.get(language)  # type: ignore[arg-type]
    assert result.document_choices == [(7, "Invoice"), (9, "Act")]


async def test_one_match_is_delivered_without_choice() -> None:
    result = await run(DocTools([doc(7, "Счёт")]), ReplayModel())
    assert result.action == Action.DELIVER_DOCUMENT
    assert result.document_choices == []


async def test_no_match_goes_to_manager_without_choice() -> None:
    result = await run(DocTools([]), ReplayModel())
    assert result.action == Action.HANDOFF
    assert result.document_choices == []


async def test_choices_are_capped() -> None:
    many = [doc(i, f"Счёт {i}") for i in range(1, 16)]
    result = await run(DocTools(many), ReplayModel(reply("—")))
    assert [i for i, _ in result.document_choices] == list(range(1, 11))
