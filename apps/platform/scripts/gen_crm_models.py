"""Модели ответов CRM для BFF из `packages/contracts/openapi/crm.yaml` (B6, ADR-0016).

OpenAPI CRM генерируется из CRM (`make -C apps/crm openapi`) и лежит в контракте; BFF разбирает ответы CRM
сгенерированными моделями Pydantic v2, а не руками по ключам словаря. Генератор тот же, что для событий шины
(`datamodel-code-generator`, версия закреплена в `uv.lock`): из схемы берутся только корни `ROOTS` и всё, что они
транзитивно подключают по `$ref`; остальной API CRM BFF не знает и модели не получает.

Результат — `apps/platform/bff/app/clients/crm_models.py`, руками не правится.

Использование (из apps/platform/bff): `uv run python ../scripts/gen_crm_models.py [--check]`;
через make: `make -C apps/platform crm-models` и `crm-models-check`; `--check` не пишет файл, а сверяет его.

Новая модель: добавить имя схемы в `ROOTS` (см. `components.schemas` в crm.yaml), запустить генерацию, закоммитить.
Контракт CRM изменился (удалена схема из ROOTS, переименовано поле) — генерация упадёт или изменит файл: так расхождение
BFF с CRM видно в том же PR, что и изменение CRM.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "packages" / "contracts" / "openapi" / "crm.yaml"
OUTPUT = REPO / "apps" / "platform" / "bff" / "app" / "clients" / "crm_models.py"
SCHEMA_REF = "#/components/schemas/"

# Ответы CRM, которые BFF разбирает моделью: вход/обновление (CrmClient.tokens) и SSO-токен для ERP (AuthService).
ROOTS = (
    "TokenResponse",
    "SsoTokenResponse",
    # Admin · Внешние интеграции (W13-A1): коннекторы ERP, Telegram, почта; реестр внешних сервисов; модели, расходы,
    # бэкапы и состояние системы. Значений секретов в этих ответах нет — только «задан» и последние 4 символа.
    "ErpStatusOut",
    "ErpCheckOut",
    "ErpPairingOut",
    "TelegramStatusOut",
    "ChatCandidateOut",
    "BotProfileOut",
    "ActionResult",
    "SmtpStatusOut",
    "SmtpCheckOut",
    "EmailLogItem",
    "EmailQueuedOut",
    "ExternalServicesOut",
    "ExternalServiceDetailOut",
    "ExternalServiceOut",
    "ModelStatus",
    "ModelChangeResult",
    "ProviderKeyResult",
    "ModelTestResult",
    "SpendReport",
    "AiSpendReport",
    "BackupsOut",
    "SystemStatusOut",
    # Первый запуск (W13-A4): состояние мастера, чек-лист, временный пароль (сброс без почты).
    "SetupState",
    "SetupChecklist",
    "PasswordReset",
    # CRM · База знаний и Admin · Настройки бота (W13-A5): документы, фрагменты, поиск, пробелы, продукты, песочница; разделы
    # настроек (значения и схемы формы), пробный прогон правил передачи, шаблоны быстрых ответов.
    "Created",
    "KbDocumentOut",
    "KbChunkOut",
    "SearchResponse",
    "KbGapPage",
    "ProductOut",
    "SandboxTurnOut",
    "SettingsResponse",
    "DryRunResponse",
    "ReplyTemplateOut",
)

HEADER = (
    "# Сгенерировано apps/platform/scripts/gen_crm_models.py из packages/contracts/openapi/crm.yaml — "
    "не править руками (make -C apps/platform crm-models)."
)
CODEGEN_ARGS = [
    "--input-file-type",
    "openapi",
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


def _refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                if not value.startswith(SCHEMA_REF):
                    raise SystemExit(f"crm.yaml: $ref {value!r} — поддерживаются только {SCHEMA_REF}<имя>")
                found.add(value.removeprefix(SCHEMA_REF))
            else:
                _refs(value, found)
    elif isinstance(node, list):
        for item in node:
            _refs(item, found)


def subset(spec: dict[str, Any], roots: tuple[str, ...]) -> dict[str, Any]:
    """Документ OpenAPI только с корневыми схемами и достижимыми по $ref."""
    schemas: dict[str, Any] = spec["components"]["schemas"]
    wanted: dict[str, Any] = {}
    queue = list(roots)
    while queue:
        name = queue.pop()
        if name in wanted:
            continue
        if name not in schemas:
            raise SystemExit(f"crm.yaml: схемы {name!r} нет — BFF ждёт её (ROOTS в gen_crm_models.py); контракт CRM изменился?")
        wanted[name] = schemas[name]
        nested: set[str] = set()
        _refs(schemas[name], nested)
        queue.extend(sorted(nested))
    return {
        "openapi": spec["openapi"],
        "info": {"title": "CRM: ответы, которые разбирает BFF", "version": str(spec["info"]["version"])},
        "paths": {},
        "components": {"schemas": {name: wanted[name] for name in sorted(wanted)}},
    }


def generate() -> str:
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "crm-subset.json", Path(tmp) / "crm_models.py"
        src.write_text(json.dumps(subset(spec, ROOTS), ensure_ascii=False, indent=2), encoding="utf-8")
        # cwd — пустой каталог: форматтеры не подхватывают конфиг ruff приложения, вывод не зависит от места запуска.
        subprocess.run(
            ["datamodel-codegen", "--input", str(src), "--output", str(out), *CODEGEN_ARGS],
            check=True,
            cwd=tmp,
        )
        return out.read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--check", action="store_true", help="не писать файл, а сверить с закоммиченным")
    args = ap.parse_args()
    text = generate()
    rel = OUTPUT.relative_to(REPO)
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            print(f"{rel} устарел — make -C apps/platform crm-models и закоммитьте", file=sys.stderr)
            return 1
        print(f"{rel}: актуален")
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"CRM → {rel} ({len(ROOTS)} корней)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
