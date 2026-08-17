"""Синхронизация классификатора ТН ВЭД с tarif.customs.uz (ГТК РУз).

Источник — тот же server-side DataTables endpoint, которым питается публичная страница
«Интегрированный тариф» (https://tarif.customs.uz/ru/directory/tnved): POST /hscode-list
со старыми параметрами DataTables 1.9 (iDisplayStart/iDisplayLength). Ответ — строки
`[код, наименование, ед.изм., доп.ед.изм.]`; наименование уже содержит полный путь по
дереву через «:», поэтому триграммный поиск подсказки работает и по родительскому контексту.

Сервер МЕДЛЕННЫЙ: ~8 строк в секунду независимо от размера страницы, полная выгрузка
(~13 тыс. кодов) занимает около получаса. Поэтому синхронизация живёт в ночной
Celery-задаче на очереди `imports`, а не в request path.

Семантика повторного прогона — как у import_hs_codes: ключ — сам код, наименования
обновляются, дубли не плодятся. Коды, исчезнувшие из выгрузки, НЕ удаляются, а
закрываются `valid_until` (старые документы должны читаться); вернувшийся код
открывается заново. Предохранитель `MIN_EXPECTED_CODES` не даёт урезанному ответу
сервера закрыть полсправочника.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

TARIF_TNVED_URL = "https://tarif.customs.uz/hscode-list"
# tarif.customs.uz отдаёт ТОЛЬКО листовой сертификат, без промежуточного Sectigo DV R36 —
# браузеры дотягивают цепочку сами (AIA), Python нет. Публичный промежуточный сертификат
# (истекает 2036) лежит рядом и докладывается в стандартное certifi-хранилище.
TARIF_INTERMEDIATE_CA = Path(__file__).resolve().parent / "certs" / "sectigo-dv-r36.pem"
TNVED_SOURCE = "tarif.customs.uz"
# ~8 строк/сек у сервера: страница в 500 строк отдаётся около минуты — таймаут с запасом.
TNVED_PAGE_SIZE = 500
TNVED_REQUEST_TIMEOUT = 300
# В номенклатуре РУз ~13 тыс. десятизначных кодов. Ответ заметно короче — это обрыв или
# поломка источника, а не реальное сокращение классификатора: такой прогон прерываем.
MIN_EXPECTED_CODES = 10_000

_DIGITS = re.compile(r"\D+")


def normalize_hs_code(raw: str) -> str:
    """Только цифры: вычищает пробелы и точки-разделители («0101 21 000 0» → «0101210000»)."""
    return _DIGITS.sub("", raw or "")


def fetch_tnved_rows(page_size: int = TNVED_PAGE_SIZE, timeout: int = TNVED_REQUEST_TIMEOUT) -> list[list]:
    """Постранично выкачивает все строки классификатора. Занимает ~30 минут (сервер медленный)."""
    import ssl

    import certifi
    import httpx

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    ssl_context.load_verify_locations(cafile=str(TARIF_INTERMEDIATE_CA))

    rows: list[list] = []
    offset = 0
    page_number = 0
    with httpx.Client(timeout=timeout, verify=ssl_context) as client:
        while True:
            page_number += 1
            response = client.post(
                TARIF_TNVED_URL,
                data={
                    "sEcho": page_number,
                    "iDisplayStart": offset,
                    "iDisplayLength": page_size,
                    "sSearch": "",
                    # Явная сортировка по коду — чтобы страницы не пересекались между запросами.
                    "iSortingCols": 1,
                    "iSortCol_0": 0,
                    "sSortDir_0": "asc",
                },
            )
            response.raise_for_status()
            payload = response.json()
            page = payload.get("aaData") or []
            rows.extend(page)
            offset += len(page)
            total = int(payload.get("iTotalRecords") or 0)
            logger.info("ТН ВЭД: страница %s, получено %s из %s", page_number, offset, total)
            if not page or offset >= total:
                return rows


def sync_tnved_codes(rows: list[list] | None = None) -> dict:
    """Синхронизирует HSCode с выгрузкой tarif.customs.uz. Возвращает сводку прогона.

    `rows` позволяет накатить заранее сохранённый ответ (см. `manage.py sync_tnved
    --from-file`) — тот же путь записи без получасовой выгрузки.
    """
    from django.db import transaction
    from django.utils import timezone

    from .models import HSCode

    if rows is None:
        rows = fetch_tnved_rows()

    parsed: dict[str, dict] = {}
    skipped = 0
    for row in rows:
        code = normalize_hs_code(str(row[0]) if row else "")
        name = str(row[1] or "").strip() if len(row) > 1 else ""
        if not code or not name or len(code) % 2:
            skipped += 1
            continue
        parsed[code] = {
            "name": name,
            "unit_name": str(row[2] or "").strip() if len(row) > 2 else "",
            "extra_unit_name": str(row[3] or "").strip() if len(row) > 3 else "",
        }

    if len(parsed) < MIN_EXPECTED_CODES:
        raise ValueError(
            f"ТН ВЭД: источник вернул {len(parsed)} кодов при ожидаемых ≥{MIN_EXPECTED_CODES} — "
            "похоже на оборванный ответ, синхронизация прервана, справочник не тронут."
        )

    today = timezone.localdate()
    now = timezone.now()
    existing = {hs_code.code: hs_code for hs_code in HSCode.objects.all()}
    # На первом наполнении valid_from не проставляем: коды действовали задолго до нас.
    initial_load = not existing

    to_create: list[HSCode] = []
    to_update: list[HSCode] = []
    for code, data in parsed.items():
        current = existing.get(code)
        if current is None:
            to_create.append(
                HSCode(
                    code=code,
                    level=len(code),
                    source=TNVED_SOURCE,
                    valid_from=None if initial_load else today,
                    **data,
                )
            )
            continue
        changed = (
            current.name != data["name"]
            or current.unit_name != data["unit_name"]
            or current.extra_unit_name != data["extra_unit_name"]
            or current.valid_until is not None
        )
        if changed:
            current.name = data["name"]
            current.unit_name = data["unit_name"]
            current.extra_unit_name = data["extra_unit_name"]
            current.valid_until = None  # код снова в действующей редакции
            current.source = TNVED_SOURCE
            current.updated_at = now
            to_update.append(current)

    # Закрываем только то, за что отвечает эта выгрузка: десятизначные действующие коды.
    # Промежуточные уровни (2/4/6/8) могли прийти из CSV-редакций — их не трогаем.
    vanished_ids = [
        hs_code.pk
        for code, hs_code in existing.items()
        if hs_code.level == 10 and hs_code.valid_until is None and code not in parsed
    ]

    with transaction.atomic():
        HSCode.objects.bulk_create(to_create, batch_size=500)
        HSCode.objects.bulk_update(
            to_update,
            ["name", "unit_name", "extra_unit_name", "valid_until", "source", "updated_at"],
            batch_size=500,
        )
        closed = HSCode.objects.filter(pk__in=vanished_ids).update(valid_until=today, updated_at=now)
        linked = link_hs_parents()

    summary = {
        "fetched": len(parsed),
        "created": len(to_create),
        "updated": len(to_update),
        "closed": closed,
        "skipped": skipped,
        "linked": linked,
    }
    logger.info("ТН ВЭД: синхронизация завершена: %s", summary)
    return summary


def link_hs_parents() -> int:
    """Иерархия выводится из самих кодов: у 10-значного родитель — ближайший более короткий."""
    from .models import HSCode

    by_code = dict(HSCode.objects.values_list("code", "id"))
    linked = 0
    for code, pk in by_code.items():
        parent_id = None
        for cut in range(len(code) - 2, 1, -2):
            parent_id = by_code.get(code[:cut])
            if parent_id:
                break
        if parent_id and parent_id != pk:
            linked += HSCode.objects.filter(pk=pk).exclude(parent_id=parent_id).update(parent_id=parent_id)
    return linked
