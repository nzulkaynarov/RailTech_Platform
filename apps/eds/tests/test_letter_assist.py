"""План 1.4: помощник письма — «Подготовить текст» и «Перевести на английский». Шлюз — подмена (`MockTransport`)."""

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from rt_docs import validate_body

from app.ai import gateway
from app.config import Settings
from tests.domain import Person
from tests.test_api_auth import assert_error

pytestmark = pytest.mark.pg


class FakeModel:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.answer: dict[str, Any] = {
            "markdown": "Уважаемый партнёр!\n\nПросим подтвердить поставку.",
            "back_translation": None,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(self.answer)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 200},
            },
            headers={gateway.COST_HEADER: "0.0002"},
        )


@pytest.fixture
def model(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    fake = FakeModel()
    monkeypatch.setattr(gateway, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(settings, "litellm_api_key", SecretStr("sk-test-eds-key"))
    return fake


async def assist(client: httpx.AsyncClient, who: Person, **body: Any) -> httpx.Response:
    return await client.post("/api/v1/letter-assist", json=body, headers=who.headers)


async def test_draft_becomes_a_valid_body(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel
) -> None:
    response = await assist(
        client, staff["manager"], action="draft", lang="ru", brief="Попросить подтвердить поставку", subject="Поставка"
    )
    assert response.status_code == 200, response.text
    body = response.json()["body"]
    validate_body(body)
    assert [b["type"] for b in body["doc"]["content"]] == ["paragraph", "paragraph"]
    assert response.json()["back_translation"] is None
    sent = model.bodies[0]
    assert sent["model"] == "draft-model"
    text = sent["messages"][1]["content"][0]["text"]
    assert "<brief>\nПопросить подтвердить поставку\n</brief>" in text and "<lang>ru</lang>" in text


async def test_translation_comes_with_a_back_translation(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel
) -> None:
    source = {
        "version": 1,
        "lang": "ru",
        "doc": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Просим подтвердить поставку."}]}],
        },
    }
    model.answer = {"markdown": "Please confirm the delivery.", "back_translation": "Просим подтвердить поставку."}
    response = await assist(client, staff["manager"], action="translate", lang="en", body=source)
    assert response.status_code == 200, response.text
    assert response.json()["body"]["lang"] == "en"
    assert response.json()["body"]["doc"]["content"][0]["content"][0]["text"] == "Please confirm the delivery."
    assert response.json()["back_translation"] == "Просим подтвердить поставку."
    assert "<letter>\nПросим подтвердить поставку.\n</letter>" in model.bodies[0]["messages"][1]["content"][0]["text"]


async def test_empty_input_and_rights(client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel) -> None:
    assert_error(
        await assist(client, staff["manager"], action="draft", lang="ru", brief="  "), 422, "VALIDATION_FAILED"
    )
    assert_error(await assist(client, staff["manager"], action="translate", lang="en"), 422, "VALIDATION_FAILED")
    assert_error(await assist(client, staff["nobody"], action="draft", lang="ru", brief="x"), 403, "FORBIDDEN")
    assert model.bodies == [], "модель не вызывалась"


async def test_without_a_key_the_helper_says_so(
    client: httpx.AsyncClient, staff: dict[str, Person], settings: Settings
) -> None:
    from pydantic import SecretStr as Secret

    settings.litellm_api_key = Secret("")
    response = await assist(client, staff["manager"], action="draft", lang="ru", brief="Письмо")
    assert_error(response, 409, "CONFLICT")
