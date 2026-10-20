"""Контракт internal API ERP (`packages/contracts/openapi/erp-internal.yaml`) из выгрузки drf-spectacular (FIX-40).

Вход — `backend/schema.json` (`manage.py spectacular`), выход (stdout) — YAML только с путями `/api/v1/`.
Портал и integration сюда не входят: у них ручные контракты (`erp-portal.yaml`, `erp-integration.yaml`),
которые ERP сверяет сторожами в тестах. Компоненты, на которые не ссылается ни один оставленный путь, отбрасываются
(иначе `redocly lint`: `no-unused-components`).

Запуск (внутри образа бэкенда, PyYAML уже стоит — его требует drf-spectacular):

    python scripts/export_internal_contract.py schema.json > ../../../packages/contracts/openapi/erp-internal.yaml

Обычно вызывается через `make -C apps/erp openapi`. Вывод детерминирован: одинаковая схема → одинаковые байты.
"""

import json
import sys

import yaml

PREFIX = "/api/v1/"
COMPONENT_REF = "#/components/"

HEADER = (
    "# СГЕНЕРИРОВАНО из drf-spectacular (apps/erp/backend/schema.json), пути /api/v1/. Руками не править:\n"
    "# make -C apps/erp openapi. Портал и integration — ручные контракты (erp-portal.yaml, erp-integration.yaml).\n"
)

INFO_OVERRIDES = {
    "title": "RailTech Platform ERP — Internal API (ERP SPA)",
    "description": (
        "Внутренний API ERP для ERP SPA (бэк-офис), пространство `/api/v1/` (CONTRACTS §1). "
        "Файл генерируется из схемы бэкенда — это не отдельное описание, а её срез; расхождение с кодом невозможно: "
        "CI перегенерирует схему и падает при diff."
    ),
}

SERVERS = [
    {"url": "https://erp.railtech.uz", "description": "prod"},
    {"url": "http://erp.localhost", "description": "стенд ансамбля (infra/compose)"},
]


def iter_refs(node):
    """Все ссылки на компоненты внутри узла: `$ref` и значения `discriminator.mapping`."""
    if isinstance(node, dict):
        for value in node.values():
            yield from iter_refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_refs(value)
    elif isinstance(node, str) and node.startswith(COMPONENT_REF):
        yield node


def split_ref(ref):
    kind, _, name = ref[len(COMPONENT_REF) :].partition("/")
    return kind, name


def reachable_components(paths, components):
    """Компоненты, достижимые из оставленных путей (транзитивно)."""
    keep = {}
    queue = list(iter_refs(paths))
    while queue:
        kind, name = split_ref(queue.pop())
        if name in keep.get(kind, {}):
            continue
        body = components.get(kind, {}).get(name)
        if body is None:
            continue
        keep.setdefault(kind, {})[name] = body
        queue.extend(iter_refs(body))
    return keep


def build(schema):
    paths = {path: item for path, item in schema["paths"].items() if path.startswith(PREFIX)}
    components = reachable_components(paths, schema.get("components", {}))
    # Схемы безопасности не достижимы по $ref — оставляем те, что названы в требованиях оставленных операций.
    used_schemes = {
        name
        for item in paths.values()
        for operation in item.values()
        if isinstance(operation, dict)
        for requirement in operation.get("security", [])
        for name in requirement
    }
    schemes = {k: v for k, v in schema.get("components", {}).get("securitySchemes", {}).items() if k in used_schemes}
    if schemes:
        components["securitySchemes"] = schemes
    used_tags = {
        tag
        for item in paths.values()
        for operation in item.values()
        if isinstance(operation, dict)
        for tag in operation.get("tags", [])
    }
    return {
        "openapi": schema["openapi"],
        "info": {**schema["info"], **INFO_OVERRIDES},
        "servers": SERVERS,
        "tags": [tag for tag in schema.get("tags", []) if tag["name"] in used_tags],
        "paths": dict(sorted(paths.items())),
        "components": {kind: dict(sorted(items.items())) for kind, items in sorted(components.items())},
    }


def _str_representer(dumper, data):
    """Многострочный текст — блоком `|`, если YAML может его представить без потерь."""
    block = "\n" in data and all(ch == "\n" or ch.isprintable() for ch in data)
    block = block and not any(line != line.rstrip() for line in data.split("\n")) and not data.startswith((" ", "\n"))
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if block else None)


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(str, _str_representer)


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: export_internal_contract.py schema.json > erp-internal.yaml")
    with open(argv[1], encoding="utf-8") as fh:
        schema = json.load(fh)
    sys.stdout.write(HEADER)
    yaml.dump(build(schema), sys.stdout, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=120)


if __name__ == "__main__":
    main(sys.argv)
