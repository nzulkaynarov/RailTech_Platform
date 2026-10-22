"""Генерация пакета rt-contracts (L6): модели Pydantic v2 событий rt_bus из JSON Schema events/.

Один генератор — datamodel-code-generator (версия закреплена в uv.lock). Результат:
    generated/python/src/rt_contracts/events/envelope.py   Envelope (конверт CloudEvents)
    generated/python/src/rt_contracts/events/<домен>.py    модели data каждого типа и общих $defs домена
    generated/python/src/rt_contracts/events/__init__.py   TYPES: тип → модель data
Детерминированно (без даты в шапке): make contracts + `git diff generated/` пуст = модели свежие.

Схемы домена собираются в одну (общие $defs один раз, тип — класс <Сущность><Действие>V<N>), поэтому ссылки
между файлами генератор не ходит по сети и не плодит копий DealRef и т. п. Модели читателя терпимы
(extra="ignore": неизвестные поля новой версии схемы не ломают старый код); строгость отправителя проверяет JSON Schema.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from contracts_events import CONTRACTS, DEFS_FILE, ENVELOPE, EVENTS, EventType, event_types, load_json

OUT = CONTRACTS / "generated" / "python" / "src" / "rt_contracts" / "events"
# Корень сборки домена генератор превращает в пустой RootModel[Any] — он не нужен.
BUNDLE_ROOT = re.compile(
    r'^class \w+\(RootModel\[Any\]\):\n    root: Annotated\[Any, Field\(title="Сборка домена \w+"\)\]\n+', re.M
)
HEADER = "# Сгенерировано scripts/gen_python.py из packages/contracts/events/ — не править руками (make contracts)."

CODEGEN_ARGS = [
    "--input-file-type",
    "jsonschema",
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--target-python-version",
    "3.12",
    "--use-standard-collections",
    "--use-union-operator",
    "--use-annotated",
    "--field-constraints",
    "--use-double-quotes",
    "--use-schema-description",
    "--use-field-description",
    "--enum-field-as-literal",
    "one",
    "--keep-model-order",
    "--disable-timestamp",
    "--custom-file-header",
    HEADER,
    "--formatters",
    "ruff-format",
    "ruff-check",
]


def _rewrite_refs(node: Any, mapping: dict[str, str]) -> Any:
    """$ref на общий файл домена (`_defs.vN.json#/$defs/X`) → локальный `#/$defs/<имя в сборке>`."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                if v not in mapping:
                    raise ValueError(f"$ref {v!r}: поддерживаются #/$defs/… и _defs.vN.json#/$defs/… своего домена")
                out[k] = mapping[v]
            else:
                out[k] = _rewrite_refs(v, mapping)
        return out
    if isinstance(node, list):
        return [_rewrite_refs(x, mapping) for x in node]
    return node


def bundle_domain(domain: str, types: list[EventType]) -> dict[str, Any]:
    """Одна схема на домен: $defs = общие определения (_defs.vN; для N>1 — с суффиксом VN) + тип на класс."""
    defs: dict[str, Any] = {}
    shared: dict[str, str] = {}  # "_defs.v1.json#/$defs/X" → "#/$defs/<имя в сборке>"
    folder = EVENTS / domain
    for f in sorted(folder.glob("_defs.v*.json")):
        m = DEFS_FILE.match(f.name)
        if not m:
            raise ValueError(f"{f}: ожидалось _defs.v<N>.json")
        suffix = "" if m["version"] == "1" else f"V{m['version']}"
        doc = load_json(f)
        names = {k: f"{k}{suffix}" for k in doc.get("$defs", {})}
        mapping = {f"#/$defs/{k}": f"#/$defs/{v}" for k, v in names.items()}
        for k, body in doc.get("$defs", {}).items():
            if names[k] in defs:
                raise ValueError(f"{f}: определение {names[k]} уже есть в домене {domain}")
            defs[names[k]] = _rewrite_refs(body, mapping)
        shared.update({f"{f.name}#/$defs/{k}": f"#/$defs/{v}" for k, v in names.items()})
    for t in types:
        schema = copy.deepcopy(load_json(t.path))
        mapping = shared | {f"#/$defs/{k}": f"#/$defs/{t.class_name}{k}" for k in schema.get("$defs", {})}
        for k, body in schema.pop("$defs", {}).items():
            defs[f"{t.class_name}{k}"] = _rewrite_refs(body, mapping)
        for key in ("$schema", "$id"):
            schema.pop(key, None)
        if t.class_name in defs:
            raise ValueError(f"{t.path}: имя класса {t.class_name} занято общим определением")
        defs[t.class_name] = _rewrite_refs(schema, mapping)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"Сборка домена {domain}",
        "$defs": defs,
    }


def codegen(schema: dict[str, Any] | Path, output: Path, *extra: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        if isinstance(schema, Path):
            src = schema
        else:
            src = Path(tmp) / "bundle.json"
            src.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        cmd = ["datamodel-codegen", "--input", str(src), "--output", str(output), *CODEGEN_ARGS, *extra]
        # cwd — пустой каталог: форматтеры не подхватывают чужой конфиг ruff, вывод не зависит от места запуска.
        subprocess.run(cmd, check=True, cwd=tmp)


def render_init(types: list[EventType]) -> str:
    domains = sorted({t.domain for t in types})
    lines = [
        HEADER,
        '"""Модели событий rt_bus: Envelope (конверт CloudEvents) и модель data для каждого типа.',
        "",
        "    from rt_contracts.events import TYPES, Envelope",
        "    env = Envelope.model_validate(body)",
        "    data = TYPES[env.type].model_validate(env.data)",
        '"""',
        "",
        "from pydantic import BaseModel",
        "",
        "from rt_contracts.events.envelope import Envelope",
    ]
    for d in domains:
        names = ", ".join(t.class_name for t in types if t.domain == d)
        lines.append(f"from rt_contracts.events.{d} import {names}")
    lines += ["", "TYPES: dict[str, type[BaseModel]] = {"]
    lines += [f'    "{t.name}": {t.class_name},' for t in types]
    lines += ["}", '"""Тип события (uz.railtech.<домен>.<сущность>.<действие>.v<N>) → модель data."""', ""]
    exported = ["Envelope", "TYPES", *sorted(t.class_name for t in types)]
    lines += ["__all__ = ["] + [f'    "{n}",' for n in exported] + ["]", ""]
    return "\n".join(lines)


def main() -> int:
    types = event_types()
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "events"
        stage.mkdir()
        codegen(ENVELOPE, stage / "envelope.py", "--class-name", "Envelope", "--extra-fields", "allow")
        for domain in sorted({t.domain for t in types}):
            bundle = bundle_domain(domain, [t for t in types if t.domain == domain])
            codegen(bundle, stage / f"{domain}.py", "--extra-fields", "ignore")
        (stage / "__init__.py").write_text(render_init(types), encoding="utf-8")
        for module in stage.glob("*.py"):
            text = BUNDLE_ROOT.sub("", module.read_text(encoding="utf-8"))
            module.write_text(text, encoding="utf-8")
        # Настройки ruff по умолчанию (cwd — временный каталог): убрать ставшие лишними импорты, отформатировать.
        ruff = ["ruff", "--quiet", "--no-cache"]
        subprocess.run([ruff[0], "check", *ruff[1:], "--fix", "--select", "F401,I", "."], check=True, cwd=stage)
        subprocess.run([ruff[0], "format", *ruff[1:], "."], check=True, cwd=stage)
        if OUT.exists():
            shutil.rmtree(OUT)
        shutil.copytree(stage, OUT)
    print(f"rt-contracts: {len(types)} типов → {OUT.relative_to(CONTRACTS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
