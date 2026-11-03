"""Запасной путь PD-BIZ: переопубликовать политику защиты данных для ИИ на шину.

    python -m app republish-ai-policy

Обычно не нужен: воркер при каждом старте сам публикует текущую политику
(`services/ai_policy_publish.py`). Повтор безопасен: EDS применяет снимок не старее прежнего.
"""

import sys

from app.container import get_container
from app.services.ai_policy_publish import republish_ai_policy


async def run() -> int:
    from app.tasks.queue import queue

    container = get_container()
    try:
        async with queue.open_async():
            policy = await republish_ai_policy(container.session_factory)
            await container.drain_bus()  # пробуждения шины — пока очередь открыта
    finally:
        await container.aclose()
    sys.stdout.write(f"Опубликована политика защиты данных для ИИ: {policy}.\n")
    return 0
