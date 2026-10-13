"""Живой вызов `dialog-model` через LiteLLM (маркер live: CI не запускает).

Запуск на dev-стенде: `docker compose ... run --rm worker pytest -m live tests/live`.
"""

import pytest

from app.agents.llm import ChatModel
from app.config import Settings
from app.integrations.litellm import make_client

pytestmark = pytest.mark.live


async def test_dialog_model_answers_in_requested_language() -> None:
    model = ChatModel(make_client(Settings()), "dialog-model", max_tokens=200)
    result = await model.complete(
        [
            {"role": "system", "content": "Отвечай одним коротким предложением на узбекском."},
            {"role": "user", "content": "Поздоровайся с клиентом."},
        ],
        name="live.dialog",
    )
    assert result.text.strip()
    assert result.tokens_out > 0
