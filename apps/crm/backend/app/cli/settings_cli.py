"""Просмотр и изменение настроек (`settings`) из CLI — до UI настроек (Фаза 5)."""

import argparse
import json
import sys

from pydantic import ValidationError

from app.container import get_container
from app.services.settings import UnknownSettingError


async def run(args: argparse.Namespace) -> int:
    container = get_container()
    service = container.settings_service
    try:
        if args.value is None:
            everything = await service.raw()
            payload: object = everything if args.key == "all" else everything.get(args.key)
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
            return 0
        current = (await service.raw()).get(args.key)
        if current is None:
            raise UnknownSettingError(args.key)
        merged = {**current, **json.loads(args.value)}
        await service.update(args.key, merged, None)
        sys.stdout.write(f"Сохранено: {args.key}\n")
        return 0
    except (UnknownSettingError, json.JSONDecodeError, ValidationError) as exc:
        sys.stderr.write(f"Ошибка: {exc}\n")
        return 1
    finally:
        await container.aclose()
