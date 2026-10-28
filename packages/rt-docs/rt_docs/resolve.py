"""Подстановка данных в тело: переменные → текст, блоки с замком → узлы данных. Общий шаг для HTML и DOCX.

Результат — то же дерево узлов контракта, но без `variable` и `block`: переменная становится узлом `text` с пометками
`_var` (код) и `_missing` (значения нет — печатается подпись из каталога), блок — узлом `_block` с содержимым.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .contracts import Catalog
from .formatters import format_value
from .model import Lang, Value

Node = dict[str, Any]


@dataclass
class Resolved:
    content: list[Node]
    missing_variables: list[str] = field(default_factory=list)
    missing_blocks: list[str] = field(default_factory=list)
    unknown_codes: list[str] = field(default_factory=list)

    def warnings(self) -> list[str]:
        out = [f"variable without value: {code}" for code in self.missing_variables]
        out += [f"block without data: {code}" for code in self.missing_blocks]
        out += [f"code not in catalog: {code}" for code in self.unknown_codes]
        return out


class _Resolver:
    def __init__(
        self,
        values: Mapping[str, Value],
        blocks: Mapping[str, Sequence[Mapping[str, Any]]],
        catalog: Catalog,
        lang: Lang,
    ) -> None:
        self.values = values
        self.blocks = blocks
        self.catalog = catalog
        self.lang = lang
        self.result = Resolved(content=[])

    def _note(self, bucket: list[str], code: str) -> None:
        if code not in bucket:
            bucket.append(code)

    def _known(self, code: str, *, block: bool) -> None:
        table = self.catalog.blocks if block else self.catalog.variables
        if self.catalog.variables and code not in table:
            self._note(self.result.unknown_codes, code)

    def value(self, code: str) -> tuple[str, bool]:
        """Текст значения и признак «нет значения» (тогда текст — подпись из каталога)."""
        self._known(code, block=False)
        raw = self.values.get(code)
        if raw is None or raw == "":
            self._note(self.result.missing_variables, code)
            return self.catalog.label(code, self.lang), True
        return format_value(raw, self.lang), False

    def text_or_var(self, item: Any) -> tuple[str, bool] | None:
        if item is None:
            return None
        if isinstance(item, Mapping):
            return self.value(str(item["var"]))
        return str(item), False

    def inline(self, nodes: Sequence[Mapping[str, Any]]) -> list[Node]:
        out: list[Node] = []
        for node in nodes:
            if node["type"] == "variable":
                code = node["attrs"]["code"]
                text, missing = self.value(code)
                out.append(
                    {
                        "type": "text",
                        "text": text,
                        "marks": list(node.get("marks", ())),
                        "_var": code,
                        "_missing": missing,
                    }
                )
            else:
                out.append(dict(node))
        return out

    def blocks_(self, nodes: Sequence[Mapping[str, Any]]) -> list[Node]:
        out: list[Node] = []
        for node in nodes:
            kind = node["type"]
            if kind in ("paragraph", "heading"):
                out.append({**node, "content": self.inline(node.get("content", ()))})
            elif kind in ("bulletList", "orderedList", "listItem", "table", "tableRow", "tableCell", "tableHeader"):
                out.append({**node, "content": self.blocks_(node.get("content", ()))})
            elif kind == "signature":
                parties = []
                for party in node["attrs"]["parties"]:
                    parties.append({key: self.text_or_var(party.get(key)) for key in ("role", "position", "name")})
                out.append({"type": "signature", "parties": parties, "stamp": bool(node["attrs"].get("stamp", False))})
            elif kind == "block":
                out.append(self.block(node))
            else:
                out.append(dict(node))
        return out

    def block(self, node: Mapping[str, Any]) -> Node:
        code = node["attrs"]["code"]
        self._known(code, block=True)
        entry = self.catalog.blocks.get(code)
        keep = bool(entry and entry.keep_with_previous)
        data = self.blocks.get(code)
        if data is not None:
            return {"type": "_block", "code": code, "keep": keep, "missing": False, "content": self.blocks_(data)}
        if node.get("content"):
            return {
                "type": "_block",
                "code": code,
                "keep": keep,
                "missing": False,
                "content": self.blocks_(node["content"]),
            }
        self._note(self.result.missing_blocks, code)
        return {
            "type": "_block",
            "code": code,
            "keep": keep,
            "missing": True,
            "label": self.catalog.label(code, self.lang),
            "content": [],
        }


def resolve(
    body: Mapping[str, Any],
    *,
    values: Mapping[str, Value],
    blocks: Mapping[str, Sequence[Mapping[str, Any]]],
    catalog: Catalog,
) -> Resolved:
    lang: Lang = body["lang"]
    resolver = _Resolver(values, blocks, catalog, lang)
    resolver.result.content = resolver.blocks_(body["doc"]["content"])
    return resolver.result


def plain_text(nodes: Sequence[Mapping[str, Any]]) -> str:
    """Весь текст разрешённого дерева (проверка глифов, поиск)."""
    parts: list[str] = []

    def walk(items: Sequence[Mapping[str, Any]]) -> None:
        for node in items:
            if node.get("type") == "text":
                parts.append(str(node["text"]))
            elif node.get("type") == "signature":
                for party in node["parties"]:
                    parts.extend(v[0] for v in party.values() if v)
            elif node.get("type") == "_block" and node.get("missing"):
                parts.append(str(node.get("label", "")))
            walk(node.get("content", ()) or ())

    walk(nodes)
    return "\n".join(parts)
