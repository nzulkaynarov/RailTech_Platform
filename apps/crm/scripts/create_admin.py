#!/usr/bin/env python3
"""Создать (или восстановить) администратора CRM на запущенном стенде.

Идемпотентно: если пользователь с таким email есть — он получает роль admin,
активируется и новый пароль. Без --password выдаётся временный пароль, который
нужно сменить при первом входе.

Примеры:
  scripts/create_admin.py --email admin@railtech.uz --name "Иван Петров"
  scripts/create_admin.py --email admin@railtech.uz --prod
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
    parser.add_argument("--email", required=True, help="email администратора (логин)")
    parser.add_argument("--name", default="Администратор", help="имя для CRM")
    parser.add_argument("--password", help="задать пароль сразу (≥ 10 символов, буквы и цифры)")
    parser.add_argument("--prod", action="store_true", help="prod-стенд (по умолчанию dev)")
    args = parser.parse_args()

    if not (ROOT / ".env").exists():
        sys.stderr.write("Нет .env — сначала запустите scripts/bootstrap_dev.sh\n")
        return 1
    overlay = "infra/docker-compose.prod.yml" if args.prod else "infra/docker-compose.dev.yml"
    command = [
        "docker",
        "compose",
        "-f",
        "infra/docker-compose.yml",
        "-f",
        overlay,
        "--env-file",
        ".env",
        "run",
        "--rm",
        "--no-deps",
        "api",
        "python",
        "-m",
        "app",
        "create-admin",
        "--email",
        args.email,
        "--name",
        args.name,
    ]
    if args.password:
        command += ["--password", args.password]
    result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603 — аргументы фиксированы
    if result.returncode != 0:
        sys.stderr.write(
            "Не получилось. Проверьте, что стенд запущен: make ps; логи: make logs s=api\n"
        )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
