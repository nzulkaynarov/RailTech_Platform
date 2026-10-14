"""Каждый вызов модели из CRM несёт теги журнала расходов LiteLLM (M3-CRM-09).

`system=crm`, `feature=<функция>`, `model=<алиас>` в `extra_body.metadata.tags` — по ним строится
экран «Расходы» (`domain/ai_spend`). Сторож по исходникам ловит новый вызов модели без тегов.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast, get_args

import httpx2
import pytest
from openai import APIConnectionError

from app.agents.llm import ChatModel
from app.integrations.litellm import EMBED_ALIAS, Embedder
from app.integrations.llm_usage import FEATURE_BY_PURPOSE, Purpose, gateway_body
from app.services import models_status

APP = Path(__file__).parents[3] / "app"


class Raw:
    def __init__(self, parsed: Any) -> None:
        self._parsed = parsed
        self.headers: dict[str, str] = {}

    def parse(self) -> Any:
        return self._parsed


class Recorder:
    """Подставной AsyncOpenAI: запоминает аргументы чата и эмбеддингов."""

    def __init__(self, dims: int = 3) -> None:
        self.sent: list[dict[str, Any]] = []
        self.dims = dims
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=self.chat_create))
        )
        self.embeddings = SimpleNamespace(
            with_raw_response=SimpleNamespace(create=self.embed_create)
        )

    async def chat_create(self, **kwargs: Any) -> Raw:
        self.sent.append(kwargs)
        message = SimpleNamespace(content="ok", tool_calls=None)
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return Raw(SimpleNamespace(choices=[choice], usage=usage, model=kwargs["model"]))

    async def embed_create(self, **kwargs: Any) -> Raw:
        self.sent.append(kwargs)
        data = [
            SimpleNamespace(index=i, embedding=[1.0] * self.dims)
            for i in range(len(kwargs["input"]))
        ]
        usage = SimpleNamespace(prompt_tokens=1)
        return Raw(SimpleNamespace(data=data, usage=usage, model=kwargs["model"]))


def tags(feature: str, alias: str) -> dict[str, Any]:
    return {"metadata": {"tags": ["system=crm", f"feature={feature}", f"model={alias}"]}}


@pytest.mark.parametrize(
    ("alias", "purpose", "feature"),
    [
        ("dialog-model", None, "dialog"),
        ("qualifier-model", None, "qualifier"),
        ("judge-model", None, "judge"),
        ("dialog-model", "assist_draft", "assist-draft"),
        ("fallback-model", "assist_improve", "assist-improve"),
    ],
)
async def test_chat_call_carries_tags(alias: str, purpose: Purpose | None, feature: str) -> None:
    client = Recorder()
    model = ChatModel(cast(Any, client), cast(Any, alias), purpose=purpose)
    await model.complete([{"role": "user", "content": "hi"}])
    assert client.sent[0]["extra_body"] == tags(feature, alias)


async def test_fallback_retry_keeps_feature_and_tags_served_alias() -> None:
    class Failing(Recorder):
        async def chat_create(self, **kwargs: Any) -> Raw:
            if kwargs["model"] == "dialog-model":
                self.sent.append(kwargs)
                raise APIConnectionError(request=httpx2.Request("POST", "http://litellm"))
            return await super().chat_create(**kwargs)

    client = Failing()
    await ChatModel(cast(Any, client), "dialog-model").complete([])
    assert [c["extra_body"] for c in client.sent] == [
        tags("dialog", "dialog-model"),
        tags("dialog", "fallback-model"),
    ]


@pytest.mark.parametrize(("call", "feature"), [("query", "kb-search"), ("documents", "kb-ingest")])
async def test_embedding_call_carries_tags(call: str, feature: str) -> None:
    embedder = Embedder(cast(Any, Recorder()))
    client = cast(Recorder, embedder._client)
    client.dims = embedder.dimensions
    if call == "query":
        await embedder.embed_query("где счёт")
    else:
        await embedder.embed_documents([("текст", "заголовок")])
    assert client.sent[0]["extra_body"] == tags(feature, EMBED_ALIAS)


@pytest.mark.parametrize("alias", ["dialog-model", "embed-model"])
async def test_probe_carries_tags(alias: str) -> None:
    client = Recorder()
    await models_status.ping(cast(Any, client), alias, None)
    assert client.sent[0]["extra_body"]["metadata"] == tags("probe", alias)["metadata"]


def test_every_purpose_has_a_feature() -> None:
    assert set(FEATURE_BY_PURPOSE) == set(get_args(Purpose))
    assert gateway_body("dialog", "dialog-model", disable_fallbacks=True) == {
        **tags("dialog", "dialog-model"),
        "disable_fallbacks": True,
    }


def _model_calls(tree: ast.AST) -> list[ast.Call]:
    """Вызовы `….chat.completions….create(…)` и `….embeddings….create(…)`."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            chain = ast.unparse(node.func)
            if node.func.attr == "create" and ("completions" in chain or "embeddings" in chain):
                out.append(node)
    return out


def test_no_model_call_in_app_without_tags() -> None:
    """Новый вызов модели без `extra_body` → строка «other» на «Расходах»: ловим до мержа."""
    found: list[str] = []
    missing: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        for call in _model_calls(ast.parse(path.read_text(encoding="utf-8"))):
            place = f"{path.relative_to(APP)}:{call.lineno}"
            found.append(place)
            if not any(k.arg == "extra_body" for k in call.keywords):
                missing.append(place)
    assert len(found) >= 4, found  # ChatModel, Embedder, проба чата и эмбеддинга
    assert missing == []
