"""Экспорт OpenAPI-схемы FastAPI (контракт CRM, SPEC §2, ADR-0016).

Использование (из backend/): uv run python ../scripts/export_openapi.py <путь>
Формат — по расширению: .yaml/.yml (packages/contracts/openapi/crm.yaml, ключи по
алфавиту) или .json. Запускается через `make openapi`; CI проверяет актуальность.
"""

import argparse
import json
import sys
from pathlib import Path

from app.config import Settings
from app.main import create_app

YAML_HEADER = (
    "# Сгенерировано из CRM (make -C apps/crm openapi) — руками не править; "
    "свежесть проверяет CI.\n"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="куда записать (.yaml или .json)")
    args = parser.parse_args()

    schema = create_app(Settings(_env_file=None, log_level="WARNING")).openapi()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix in {".yaml", ".yml"}:
        # Импорт здесь: pre-commit корня и ruff backend по-разному сортируют yaml и app.
        import yaml

        dumped = yaml.safe_dump(schema, allow_unicode=True, sort_keys=True, width=120)
        text = YAML_HEADER + dumped
    else:
        text = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.write_text(text, encoding="utf-8")
    sys.stdout.write(f"OpenAPI → {args.output}\n")


if __name__ == "__main__":
    main()
