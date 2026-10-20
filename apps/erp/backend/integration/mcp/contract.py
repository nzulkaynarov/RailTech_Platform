"""Реестр инструментов erp-mcp = `packages/contracts/mcp-tools.json` (FIX-36, S-12).

Имена, описания, режимы и `input_schema` читаются из контракта при старте процесса; копии в коде нет.
Файл не вшит в образ, а монтируется в контейнер (infra/compose/base.yml) в `/packages/contracts` — туда же его
монтирует `apps/erp/scripts/test_backend_local.sh`, поэтому тесты и сервис читают один и тот же файл.
Нет файла или он испорчен — процесс не стартует (и тест падает), а не работает с пустым списком инструментов.

Порядок поиска: `settings.ERP_MCP_TOOLS_PATH` (env `ERP_MCP_TOOLS_PATH`), затем `/packages/contracts/mcp-tools.json`,
затем `packages/contracts/mcp-tools.json` в любом родительском каталоге этого файла (запуск из клонa репозитория).
"""

from __future__ import annotations

import dataclasses
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from django.conf import settings
from jsonschema import Draft202012Validator

CONTRACT_RELATIVE: Final = Path("packages") / "contracts" / "mcp-tools.json"
MOUNTED_PATH: Final = Path("/packages/contracts/mcp-tools.json")

NOT_FOUND_HINT: Final = (
    "Контракт packages/contracts/mcp-tools.json не найден. В контейнере он монтируется только на чтение в "
    "/packages/contracts (infra/compose/base.yml, apps/erp/scripts/test_backend_local.sh) или задаётся "
    "переменной ERP_MCP_TOOLS_PATH."
)


class ContractError(RuntimeError):
    """Контракт инструментов недоступен или не годится для сервера."""


@dataclasses.dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    modes: tuple[str, ...]
    input_schema: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class ToolsContract:
    version: str
    path: str
    tools: dict[str, ToolSpec]


def contract_path() -> Path:
    configured = (getattr(settings, "ERP_MCP_TOOLS_PATH", "") or "").strip()
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise ContractError(f"ERP_MCP_TOOLS_PATH={configured!r}: файла нет. {NOT_FOUND_HINT}")
        return path
    if MOUNTED_PATH.is_file():
        return MOUNTED_PATH
    for parent in Path(__file__).resolve().parents:
        candidate = parent / CONTRACT_RELATIVE
        if candidate.is_file():
            return candidate
    raise ContractError(NOT_FOUND_HINT)


def parse_contract(raw: dict[str, Any]) -> ToolsContract:
    tools: dict[str, ToolSpec] = {}
    for item in raw["tools"]:
        schema = item["input_schema"]
        Draft202012Validator.check_schema(schema)
        spec = ToolSpec(
            name=item["name"],
            description=item["description"],
            modes=tuple(item["modes"]),
            input_schema=schema,
        )
        if spec.name in tools:
            raise ContractError(f"инструмент {spec.name!r} объявлен в контракте дважды")
        tools[spec.name] = spec
    if not tools:
        raise ContractError("в контракте нет ни одного инструмента")
    return ToolsContract(version=str(raw["version"]), path=str(raw["path"]), tools=tools)


@lru_cache(maxsize=1)
def load_contract() -> ToolsContract:
    path = contract_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return parse_contract(raw)
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(f"контракт {path} не разобран: {exc.__class__.__name__}") from exc
