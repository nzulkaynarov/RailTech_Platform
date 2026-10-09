"""Экспорт OpenAPI-схемы FastAPI в JSON (контракт для фронта, SPEC §2).

Использование (из backend/): uv run python ../scripts/export_openapi.py <путь>
Запускается через `make openapi`; CI проверяет, что файл актуален.
"""

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="куда записать openapi.json")
    args = parser.parse_args()

    schema = create_app(Settings(_env_file=None, log_level="WARNING")).openapi()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI → {args.output}")  # noqa: T201 — CLI-вывод


if __name__ == "__main__":
    main()
