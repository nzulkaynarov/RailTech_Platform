#!/usr/bin/env python3
"""Webhook prod-бота: показать состояние, переустановить или снять (PLAN Фаза 8).

API ставит webhook сам при старте; скрипт нужен для диагностики «бот молчит»
и после смены домена/TELEGRAM_WEBHOOK_SECRET. Выполняется в контейнере api.

Примеры:
  scripts/set_webhook.py            # info: url, очередь, последняя ошибка Telegram
  scripts/set_webhook.py set        # переустановить из TELEGRAM_WEBHOOK_URL/SECRET
  scripts/set_webhook.py delete     # снять (например, перед переходом на polling)
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", nargs="?", default="info", choices=["info", "set", "delete"])
    parser.add_argument("--dev", action="store_true", help="dev-стенд (по умолчанию prod)")
    args = parser.parse_args()
    if not (ROOT / ".env").exists():
        sys.stderr.write("Нет .env в корне репозитория\n")
        return 1
    overlay = "infra/docker-compose.dev.yml" if args.dev else "infra/docker-compose.prod.yml"
    command = [
        *("docker", "compose", "-f", "infra/docker-compose.yml", "-f", overlay),
        *("--env-file", ".env", "exec", "-T", "api"),
        *("python", "-m", "app", "telegram-webhook", args.action),
    ]
    result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603 — аргументы фиксированы
    if result.returncode != 0:
        sys.stderr.write(
            "Не удалось: api запущен? (make ps). Runbook: docs/runbooks/crm/bot-silent.md\n"
        )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
