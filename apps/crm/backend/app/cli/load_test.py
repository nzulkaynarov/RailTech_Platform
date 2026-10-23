"""`python -m app load-test` — нагрузочный smoke диалогов (PLAN Фаза 8, задача 7).

N параллельных синтетических клиентов (по умолчанию 50) проходят /start → согласие →
несколько вопросов через тот же `ConversationService`, что и бот (модели, MCP, KB,
постановка квалификатора), без отправки в Telegram. Гейт: p95 хода ≤ 6 с, очередь
после паузы вернулась к исходной. Синтетические лиды затем удаляются.
⚠️ Реальные вызовы моделей (≈ N × turns ходов) — запускать на dev/стенде с тестовым каналом.
"""

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Final

from sqlalchemy import delete, select

from app.bot.setup import build_conversation, checkpointer
from app.container import get_container
from app.models.leads import Lead, TelegramIdentity
from app.repositories import monitoring
from app.services.conversation import ConversationService, Incoming
from app.tasks.lifespan import queue_lifespan

SYNTHETIC_BASE: Final = 990_000_000_000  # вне диапазона реальных Telegram id
P95_LIMIT_S: Final = 6.0
QUEUE_SLACK: Final = 5
QUESTIONS: Final = (
    "Здравствуйте! Чем вы занимаетесь?",
    "Сколько времени занимает подключение касс к 1С?",
    "Как часто обновляется местоположение вагона в RT-Track?",
    "Какие онлайн-кассы вы поддерживаете?",
    "Работаете ли вы с регионами Узбекистана?",
    "Есть ли пробный период?",
)


@dataclass(frozen=True)
class LoadReport:
    dialogs: int
    turns: int
    errors: int
    p50_s: float
    p95_s: float
    max_s: float
    queue_before: int
    queue_after: int
    passed: bool


def percentile(values: list[float], q: float) -> float:
    """Перцентиль методом nearest-rank (без интерполяции)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def summarize(
    dialogs: int, latencies: list[float], errors: int, queue_before: int, queue_after: int
) -> LoadReport:
    p95 = percentile(latencies, 95)
    ok = errors == 0 and p95 <= P95_LIMIT_S and queue_after <= queue_before + QUEUE_SLACK
    return LoadReport(
        dialogs=dialogs,
        turns=len(latencies) + errors,
        errors=errors,
        p50_s=round(percentile(latencies, 50), 2),
        p95_s=round(p95, 2),
        max_s=round(max(latencies, default=0.0), 2),
        queue_before=queue_before,
        queue_after=queue_after,
        passed=ok,
    )


async def _dialog(svc: ConversationService, index: int, turns: int) -> tuple[list[float], int]:
    user = SYNTHETIC_BASE + index
    await svc.start(Incoming(tg_user_id=user, chat_id=user, text="/start", language_code="ru"))
    await svc.accept_consent(user)
    latencies, errors = [], 0
    for turn in range(turns):
        text = QUESTIONS[(index + turn) % len(QUESTIONS)]
        started = time.monotonic()
        try:
            await svc.handle_message(Incoming(tg_user_id=user, chat_id=user, text=text))
        except Exception:  # noqa: BLE001 — ошибка хода считается в отчёте
            errors += 1
            continue
        latencies.append(time.monotonic() - started)
    return latencies, errors


async def _cleanup() -> int:
    c = get_container()
    synthetic = TelegramIdentity.tg_user_id >= SYNTHETIC_BASE
    async with c.session_factory() as session, session.begin():
        lead_ids = (await session.scalars(select(TelegramIdentity.lead_id).where(synthetic))).all()
        await session.execute(delete(TelegramIdentity).where(synthetic))
        ids = [i for i in lead_ids if i is not None]
        if ids:
            await session.execute(delete(Lead).where(Lead.id.in_(ids)))
    return len(lead_ids)


async def _queue_size() -> int:
    async with get_container().session_factory() as session:
        return await monitoring.queue_size(session)


async def run(args: argparse.Namespace) -> int:
    if not args.yes:
        print(f"Будет ≈{args.dialogs * args.turns} ходов с реальными моделями. Добавьте --yes.")  # noqa: T201
        return 2
    from app.bot.process import (
        qualify_hook as _qualify,
    )  # тот же хук, что у бота: квалификатор в очередь

    c = get_container()
    await _cleanup()
    before = await _queue_size()
    async with queue_lifespan(c.settings), checkpointer(c) as saver:
        svc = build_conversation(c, saver, on_activity=_qualify)
        results = await asyncio.gather(*(_dialog(svc, i, args.turns) for i in range(args.dialogs)))
    await asyncio.sleep(args.settle)
    report = summarize(
        args.dialogs,
        [t for latencies, _ in results for t in latencies],
        sum(e for _, e in results),
        before,
        await _queue_size(),
    )
    if not args.keep:
        await _cleanup()
    await c.engine.dispose()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))  # noqa: T201
    verdict = f"FAIL: нужно p95 ≤ {P95_LIMIT_S} с, без ошибок, очередь ≤ +{QUEUE_SLACK}"
    print("PASS" if report.passed else verdict)  # noqa: T201
    return 0 if report.passed else 1
