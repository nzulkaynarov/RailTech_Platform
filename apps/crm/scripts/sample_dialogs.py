#!/usr/bin/env python3
"""Еженедельная выгрузка случайных диалогов для разметки менеджерами (PLAN Фаза 7).

Запускает `python -m app sample-dialogs` в контейнере worker и сохраняет YAML
в reports/labeling/YYYY-MM-DD.yaml. PII (телефоны, e-mail, ИНН) замаскированы.
Формат разметки и перенос в golden — docs/evals/labeling.md.

Примеры:
  scripts/sample_dialogs.py                 # dev, 20 диалогов за 7 дней
  scripts/sample_dialogs.py --prod --count 30 --days 14
"""

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=7, help="за сколько дней (7)")
    parser.add_argument("--count", type=int, default=20, help="сколько диалогов (20)")
    parser.add_argument("--seed", type=int, help="seed выборки (для повтора)")
    parser.add_argument("--prod", action="store_true", help="prod-стенд (по умолчанию dev)")
    parser.add_argument("--out", type=Path, help="файл результата")
    args = parser.parse_args()

    if not (ROOT / ".env").exists():
        sys.stderr.write("Нет .env — сначала запустите scripts/bootstrap_dev.sh\n")
        return 1
    overlay = "infra/docker-compose.prod.yml" if args.prod else "infra/docker-compose.dev.yml"
    command = [
        *("docker", "compose", "-f", "infra/docker-compose.yml", "-f", overlay),
        *("--env-file", ".env", "run", "--rm", "--no-deps", "-T", "worker"),
        *("python", "-m", "app", "sample-dialogs"),
        *("--days", str(args.days), "--count", str(args.count)),
    ]
    if args.seed is not None:
        command += ["--seed", str(args.seed)]
    out = args.out or ROOT / "reports" / "labeling" / f"{datetime.now(UTC):%Y-%m-%d}.yaml"
    result = subprocess.run(  # noqa: S603 — аргументы фиксированы
        command, cwd=ROOT, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-2000:])
        sys.stderr.write("\nВыгрузка не удалась: проверьте `make ps` и логи worker (make logs).\n")
        return result.returncode
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.stdout, encoding="utf-8")
    sys.stdout.write(
        f"Готово: {out}\nДальше: раздайте файл менеджерам, заполните `label`; кейсы с\n"
        "golden: true перенесите в backend/evals/golden/ (docs/evals/labeling.md).\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
