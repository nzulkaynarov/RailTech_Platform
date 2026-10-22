"""OpenAPI: «ломающее → красный» (scripts/openapi_compat.py, oasdiff): фикстуры «было/стало», мажор, исключения.

Настоящий oasdiff (закреплённая версия: OASDIFF_BIN или Docker) на парах файлов; без него тесты падают,
а не пропускаются (зелёный CI без проверки хуже красного).
"""

from __future__ import annotations

import copy
import datetime as dt
import tempfile
from pathlib import Path
from typing import Any

import openapi_compat as oc
import pytest
import yaml
from openapi_compat import Change, Exemption

TODAY = dt.date(2026, 10, 23)

BASE: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "t", "version": "1.2.0"},
    "paths": {
        "/api/v1/items": {
            "get": {
                "operationId": "listItems",
                "parameters": [
                    {
                        "name": "kind",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "enum": ["a", "b", "c"]},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["id", "name"],
                                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            },
            "post": {
                "operationId": "createItem",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"type": "object", "properties": {"name": {"type": "string"}}}}
                    }
                },
                "responses": {"201": {"description": "created"}},
            },
        },
        "/api/v1/legacy": {"get": {"operationId": "legacy", "responses": {"200": {"description": "ok"}}}},
    },
}


def mutated(mutate: Any) -> dict[str, Any]:
    spec = copy.deepcopy(BASE)
    mutate(spec)
    return spec


def _remove_path(s: dict[str, Any]) -> None:
    del s["paths"]["/api/v1/legacy"]


def _remove_response_field(s: dict[str, Any]) -> None:
    schema = s["paths"]["/api/v1/items"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    del schema["properties"]["name"]
    schema["required"].remove("name")


def _required_request_field(s: dict[str, Any]) -> None:
    schema = s["paths"]["/api/v1/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    schema["required"] = ["name"]


def _narrow_enum(s: dict[str, Any]) -> None:
    s["paths"]["/api/v1/items"]["get"]["parameters"][0]["schema"]["enum"] = ["a", "b"]


def _add_optional_and_path(s: dict[str, Any]) -> None:
    props = s["paths"]["/api/v1/items"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "properties"
    ]
    props["note"] = {"type": "string"}
    s["paths"]["/api/v1/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"][
        "kind"
    ] = {"type": "string"}
    s["paths"]["/api/v1/new"] = {"get": {"operationId": "newOp", "responses": {"200": {"description": "ok"}}}}


def _add_v2(s: dict[str, Any]) -> None:
    s["info"]["version"] = "2.0.0"
    s["paths"]["/api/v2/items"] = {"get": {"operationId": "listItemsV2", "responses": {"200": {"description": "ok"}}}}


BREAKING = {
    "удалён путь": (_remove_path, "api-path-removed-without-deprecation"),
    "удалено обязательное поле ответа": (_remove_response_field, "response-required-property-removed"),
    "новое обязательное поле запроса": (_required_request_field, "request-property-became-required"),
    "сужен enum": (_narrow_enum, "request-parameter-enum-value-removed"),
}


def diff(old: dict[str, Any], new: dict[str, Any], tmp: Path) -> list[Change]:
    work = Path(
        tempfile.mkdtemp(dir=tmp)
    )  # новый каталог на пару: bind-mount Docker Desktop иногда отдаёт старое содержимое
    base, head = work / "base-x.yaml", work / "head-x.yaml"
    base.write_text(yaml.safe_dump(old), encoding="utf-8")
    head.write_text(yaml.safe_dump(new), encoding="utf-8")
    return oc.run_oasdiff(base, head)


def verdict(old: dict[str, Any], new: dict[str, Any], tmp: Path, exemptions: list[Exemption] | None = None):
    used: set[int] = set()
    errors, warnings, notes = oc.check_file("x.yaml", old, new, diff(old, new, tmp), exemptions or [], TODAY, used)
    return errors, warnings, notes, used


# ─── ломающее без нового мажора — красный ──────────────────────────────────────────────────────


@pytest.mark.parametrize(("mutate", "check_id"), BREAKING.values(), ids=list(BREAKING))
def test_breaking_change_is_red(mutate: Any, check_id: str, tmp_path: Path) -> None:
    errors, _, _, _ = verdict(BASE, mutated(mutate), tmp_path)
    assert errors, "ломающее изменение прошло как совместимое"
    assert any(f"[{check_id}]" in e for e in errors), errors


def test_narrowed_enum_inside_all_of_is_red(tmp_path: Path) -> None:
    """oasdiff сравнивает allOf по ветвям и снижает ERR до WARN; --flatten-allof возвращает красный."""

    def with_all_of(enum: list[str]) -> dict[str, Any]:
        spec = copy.deepcopy(BASE)
        spec["components"] = {
            "schemas": {
                "Fields": {"type": "object", "properties": {"channel": {"type": "string", "enum": enum}}},
                "Body": {"allOf": [{"$ref": "#/components/schemas/Fields"}, {"type": "object"}]},
            }
        }
        body = spec["paths"]["/api/v1/items"]["post"]["requestBody"]["content"]["application/json"]
        body["schema"] = {"$ref": "#/components/schemas/Body"}
        return spec

    errors = verdict(with_all_of(["a", "b"]), with_all_of(["a"]), tmp_path)[0]
    assert errors and "enum-value-removed" in errors[0], errors


def test_unchanged_and_additive_are_green(tmp_path: Path) -> None:
    assert verdict(BASE, copy.deepcopy(BASE), tmp_path)[0] == []
    assert verdict(BASE, mutated(_add_optional_and_path), tmp_path)[0] == []


def test_removal_after_deprecation_and_sunset_is_green(tmp_path: Path) -> None:
    def deprecate(s: dict[str, Any]) -> None:
        op = s["paths"]["/api/v1/legacy"]["get"]
        op["deprecated"] = True
        op["x-sunset"] = "2020-01-01"  # срок отказа давно прошёл

    deprecated = mutated(deprecate)
    assert verdict(deprecated, mutated(lambda s: (deprecate(s), _remove_path(s))), tmp_path)[0] == []
    # Пометка есть, но срок отказа ещё не настал — красное.
    soon = mutated(deprecate)
    soon["paths"]["/api/v1/legacy"]["get"]["x-sunset"] = "2099-01-01"
    errors = verdict(soon, mutated(_remove_path), tmp_path)[0]
    assert errors and "before-sunset" in errors[0], errors


def test_new_file_is_not_breaking(tmp_path: Path) -> None:
    errors, _, notes = oc.check_file("x.yaml", None, BASE, [], [], TODAY, set())
    assert errors == [] and "новый файл" in notes[0]


# ─── мажор ───────────────────────────────────────────────────────────────────────────────────


def test_major_bump_with_new_path_allows_breaking(tmp_path: Path) -> None:
    def to_v2(s: dict[str, Any]) -> None:
        _remove_path(s)
        _add_v2(s)

    errors, _, notes, _ = verdict(BASE, mutated(to_v2), tmp_path)
    assert errors == []
    assert any("api-path-removed-without-deprecation" in n and "/v2" in n for n in notes), notes


def test_major_bump_without_new_path_is_red(tmp_path: Path) -> None:
    def only_version(s: dict[str, Any]) -> None:
        _remove_path(s)
        s["info"]["version"] = "2.0.0"

    assert verdict(BASE, mutated(only_version), tmp_path)[0]


def test_new_path_without_major_bump_is_red(tmp_path: Path) -> None:
    def only_path(s: dict[str, Any]) -> None:
        _remove_path(s)
        s["paths"]["/api/v2/items"] = {"get": {"operationId": "v2", "responses": {"200": {"description": "ok"}}}}

    assert verdict(BASE, mutated(only_path), tmp_path)[0]


def test_major_helpers() -> None:
    assert oc.info_major({"info": {"version": "0.9.1"}}) == 0
    assert oc.info_major({"info": {"version": "v3.0"}}) == 3
    assert oc.path_majors(
        {"paths": {"/api/v1/a": {}, "/api/integration/v1/b": {}, "/health": {}, "/api/v2/c": {}}}
    ) == {
        1: {"/api/v1/a", "/api/integration/v1/b"},
        2: {"/api/v2/c"},
    }


# ─── исключения ───────────────────────────────────────────────────────────────────────────────


def _exemption(**kw: Any) -> Exemption:
    base = {
        "file": "x.yaml",
        "id": "api-path-removed-without-deprecation",
        "path": "/api/v1/legacy",
        "reason": "потребителей нет",
        "until": dt.date(2026, 12, 31),
    }
    return Exemption(**{**base, **kw})


def test_exception_allows_one_listed_change(tmp_path: Path) -> None:
    errors, _, notes, used = verdict(BASE, mutated(_remove_path), tmp_path, [_exemption()])
    assert errors == [] and used == {0}
    assert any("исключение до 2026-12-31" in n for n in notes)


def test_exception_does_not_cover_other_changes(tmp_path: Path) -> None:
    def two(s: dict[str, Any]) -> None:
        _remove_path(s)
        _narrow_enum(s)

    errors, _, _, _ = verdict(BASE, mutated(two), tmp_path, [_exemption()])
    assert len(errors) == 1 and "enum" in errors[0]


def test_exception_other_path_or_file_does_not_apply(tmp_path: Path) -> None:
    for ex in (_exemption(path="/api/v1/other"), _exemption(file="other.yaml"), _exemption(operation="POST")):
        assert verdict(BASE, mutated(_remove_path), tmp_path, [ex])[0]


def test_expired_exception_is_red(tmp_path: Path) -> None:
    errors, _, _, _ = verdict(BASE, mutated(_remove_path), tmp_path, [_exemption(until=dt.date(2026, 10, 1))])
    assert errors and "просрочено" in errors[0]


def test_load_exemptions(tmp_path: Path) -> None:
    f = tmp_path / "ex.yaml"
    f.write_text(
        "exceptions:\n  - {file: crm.yaml, id: x, path: /p, operation: post, reason: why, until: 2026-12-31}\n",
        encoding="utf-8",
    )
    [ex] = oc.load_exemptions(f)
    assert ex.until == dt.date(2026, 12, 31) and ex.matches("crm.yaml", Change("x", 3, "", "POST", "/p"))
    f.write_text("exceptions:\n  - {file: crm.yaml, id: x}\n", encoding="utf-8")
    with pytest.raises(oc.CompatError):
        oc.load_exemptions(f)
    assert oc.load_exemptions(tmp_path / "нет.yaml") == []


def test_repository_exceptions_file_is_valid() -> None:
    oc.load_exemptions()


# ─── целиком: база из git, файлы на диске ──────────────────────────────────────────────────────


def test_check_all_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    head = tmp_path / "x.yaml"
    head.write_text(yaml.safe_dump(mutated(_remove_path)), encoding="utf-8")
    monkeypatch.setattr(oc, "base_text", lambda ref, name: yaml.safe_dump(BASE))
    report = oc.check_all("origin/main", exemptions=[], today=TODAY, files=[head])
    assert len(report.errors) == 1 and "legacy" in report.errors[0]

    head.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    assert oc.check_all("origin/main", exemptions=[], today=TODAY, files=[head]).errors == []

    monkeypatch.setattr(oc, "base_text", lambda ref, name: None)
    report = oc.check_all("origin/main", exemptions=[], today=TODAY, files=[head])
    assert report.errors == [] and "новый файл" in report.notes[0]


def test_missing_oasdiff_is_not_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OASDIFF_BIN", raising=False)
    monkeypatch.setattr(oc.shutil, "which", lambda _: None)
    with pytest.raises(oc.CompatError, match="нет oasdiff"):
        oc.run_oasdiff(tmp_path / "a.yaml", tmp_path / "b.yaml")
