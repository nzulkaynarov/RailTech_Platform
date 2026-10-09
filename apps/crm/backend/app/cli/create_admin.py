"""Первый администратор CRM (PLAN Фаза 4). Идемпотентно: повторный запуск сбрасывает пароль."""

import argparse
import sys

from app.container import get_container
from app.domain.errors import DomainError


async def run(args: argparse.Namespace) -> int:
    container = get_container()
    try:
        password = await container.user_service.bootstrap_admin(
            args.email, args.name, args.password
        )
    except DomainError as exc:
        sys.stderr.write(f"Ошибка: {exc.message}\n")
        return 1
    finally:
        await container.aclose()
    if args.password:
        sys.stdout.write(f"Администратор {args.email} готов. Пароль — указанный вами.\n")
    else:
        sys.stdout.write(
            f"Администратор {args.email} готов.\n"
            f"Временный пароль (показывается один раз): {password}\n"
            "При первом входе система попросит сменить пароль.\n"
        )
    sys.stdout.write(
        "Дальше: откройте CRM и войдите; создайте менеджеров в разделе «Пользователи».\n"
    )
    return 0
