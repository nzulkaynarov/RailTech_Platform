"""Таможенные платежи по коду ТН ВЭД — ВИТРИНА интегрированного тарифа ГТК РУз.

ПОЧЕМУ НЕ ХРАНИМ. Ставки меняются постановлениями, зависят от страны происхождения и
преференций, а их показ из собственной базы читался бы как таможенная консультация —
с нашей ответственностью за устаревшую цифру. Эталоны (SAP GTS, Avalara, ONESOURCE)
не перепечатывают тариф, а покупают живой контент; Odoo и Bitrix24 не хранят его вовсе.
Поэтому здесь нет ни модели, ни снимка: запрос по требованию, суточный кэш, подпись
источника и ссылка на первоисточник в интерфейсе.

ИСТОЧНИК. `POST /calc/view_calc.jsp` — тот же endpoint, которым питается публичный
калькулятор на tarif.customs.uz. Отвечает HTML-фрагментом за ~1 секунду (в отличие от
получасовой выгрузки классификатора), поэтому запрос синхронный: жёсткий таймаут плюс
кэш держат путь запроса коротким, и городить Celery с 202-опросом ради секунды незачем.

ЧТО ПАРСИМ. Первая таблица — платежи (`код: название | ставка | правовое основание`),
вторая — разрешительные документы (`орган | документ | основание | вид`). Ключ строки —
ЦИФРОВОЙ КОД платежа (10 сбор, 20 пошлина, 27 акциз, 29 НДС): подписи источник отдаёт
по-узбекски даже при запросе русской локали, поэтому названия берём свои, из i18n.
Строки без кода (например утилизационный сбор на автомобили) не выбрасываем — это
реальные деньги импортёра; показываем их подпись как есть, с пометкой источника.

ПУСТАЯ СТАВКА — ЭТО НЕ НОЛЬ. Источник оставляет ячейку пустой и когда платежа нет, и
когда ставка в тарифе не задана. Мы передаём пустоту как пустоту (`rate=""`), а
интерфейс рисует «—»: «0%» здесь было бы додумыванием за таможню.
"""

from __future__ import annotations

import html
import logging
import os
import re

logger = logging.getLogger(__name__)

TARIF_CALC_URL = "https://tarif.customs.uz/calc/view_calc.jsp"
# Синхронный вызов в пути запроса обязан быть ОГРАНИЧЕН по времени: сервер ГТК отвечает
# примерно за 2 секунды, но он же отдаёт классификатор со скоростью 8 строк/сек, и рассчитывать
# на его стабильность нельзя. Порог вынесен в окружение (как `AI_REQUEST_TIMEOUT`), чтобы
# эксплуатация могла поднять его без правки кода; превышение — не ошибка, а деградация.
CALC_REQUEST_TIMEOUT = float((os.environ.get("CUSTOMS_TARIF_TIMEOUT") or "10").strip() or "10")
# Ставки живут постановлениями, а не часами: сутки кэша честны и снимают нагрузку с
# небыстрого сервера ГТК. Отрицательный кэш короткий — чтобы разовый сбой не выключал
# панель на сутки, но и не долбить лежащий источник каждым кликом.
CALC_CACHE_TTL = 60 * 60 * 24
CALC_NEGATIVE_CACHE_TTL = 60 * 5
CALC_CACHE_PREFIX = "customs-duties"

# Режим перемещения в терминах источника. Клин у нас импортный; экспорт добавится
# параметром, когда появится сценарий.
REGIME_IMPORT = "1"
UZBEKISTAN_NUMERIC = "860"

# Цифровые коды платежей ГТК — стабильный ключ строки. Подписи — наши (`customs.payment.*`
# в ru/en.json), потому что источник отдаёт узбекские вне зависимости от запрошенной локали.
PAYMENT_CUSTOMS_FEE = "10"
PAYMENT_DUTY = "20"
PAYMENT_EXCISE = "27"
PAYMENT_VAT = "29"
KNOWN_PAYMENT_CODES = {PAYMENT_CUSTOMS_FEE, PAYMENT_DUTY, PAYMENT_EXCISE, PAYMENT_VAT}

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TABLE_RE = re.compile(r"<table.*?</table>", re.S | re.I)
_ROW_RE = re.compile(r"<tr.*?</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_PAYMENT_CODE_RE = re.compile(r"^\s*(\d+)\s*:\s*(.*)$")


class DutiesUnavailable(Exception):
    """Источник не ответил или отдал неузнаваемую структуру — панель деградирует в ссылку."""


def _text(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", raw))).strip()


def _rows(table_html: str) -> list[list[str]]:
    return [[_text(cell) for cell in _CELL_RE.findall(row)] for row in _ROW_RE.findall(table_html)]


def parse_duties(document: str) -> dict:
    """HTML-фрагмент калькулятора → `{payments: [...], permits: [...]}`.

    Парсер терпимый: неузнанные строки пропускает с предупреждением, чтобы смена вёрстки
    источника не превращалась в 500. Если не найдено ни одной таблицы — это уже не
    «изменилась строка», а другой ответ целиком: поднимаем `DutiesUnavailable`.
    """
    tables = _TABLE_RE.findall(_SCRIPT_RE.sub("", document or ""))
    if not tables:
        raise DutiesUnavailable("в ответе источника нет ни одной таблицы")

    payments = []
    for cells in _rows(tables[0])[1:]:  # первая строка — заголовок
        if len(cells) < 3 or not cells[0]:
            continue
        match = _PAYMENT_CODE_RE.match(cells[0])
        code, source_label = (match.group(1), match.group(2)) if match else ("", cells[0])
        if code and code not in KNOWN_PAYMENT_CODES:
            logger.info("Пошлины: незнакомый код платежа %s (%s) — показываем подпись источника", code, source_label)
        payments.append(
            {
                "code": code,
                "source_label": source_label,
                "rate": cells[1],
                "legal_basis": cells[2],
            }
        )

    permits = []
    if len(tables) > 1:
        for cells in _rows(tables[1])[1:]:
            # «Ma'lumot topilmadi» — их строка-заглушка «ничего не найдено», у неё одна ячейка.
            if len(cells) < 4 or not cells[0]:
                continue
            permits.append(
                {
                    "organization": cells[0],
                    "document": cells[1],
                    "legal_basis": cells[2],
                    "document_kind": cells[3],
                }
            )

    if not payments:
        raise DutiesUnavailable("таблица платежей пуста — структура источника изменилась")
    return {"payments": payments, "permits": permits}


def fetch_duties(hs_code: str, origin_numeric: str, timeout: int = CALC_REQUEST_TIMEOUT) -> dict:
    """Запрашивает интегрированный тариф по коду и стране происхождения (без кэша)."""
    import ssl

    import certifi
    import httpx

    from .tnved import TARIF_INTERMEDIATE_CA

    # Тот же изъян TLS, что и у классификатора: сервер не отдаёт промежуточный сертификат,
    # браузер дотягивает цепочку по AIA, Python — нет. Сертификат уже лежит в репозитории.
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    ssl_context.load_verify_locations(cafile=str(TARIF_INTERMEDIATE_CA))

    payload = {
        "tnved": hs_code,
        "rejim": REGIME_IMPORT,
        "sending_country": origin_numeric,
        "receiving_country": UZBEKISTAN_NUMERIC,
        "orign_country": origin_numeric,  # опечатка в имени поля — на стороне источника
        "trade_country": origin_numeric,
        "lang": "ru_Ru",
    }
    try:
        with httpx.Client(timeout=timeout, verify=ssl_context) as client:
            response = client.post(TARIF_CALC_URL, data=payload)
            response.raise_for_status()
            document = response.text
    except Exception as exc:  # httpx поднимает целое семейство ошибок сети/HTTP
        raise DutiesUnavailable(f"источник не ответил: {exc}") from exc
    return parse_duties(document)


def get_duties(hs_code: str, origin_numeric: str) -> dict:
    """Платежи по коду и стране происхождения через суточный кэш.

    Возвращает `{payments, permits, fetched_at, source_url}`. Поднимает `DutiesUnavailable`,
    когда источник недоступен — вызывающий отвечает 503, а интерфейс показывает карточку
    деградации со ссылкой на калькулятор ГТК (тупика у пользователя не возникает).
    """
    from django.core.cache import cache
    from django.utils import timezone

    key = f"{CALC_CACHE_PREFIX}:{hs_code}:{origin_numeric}"
    cached = cache.get(key)
    if cached is not None:
        if cached == "unavailable":
            raise DutiesUnavailable("источник недавно не ответил (отрицательный кэш)")
        return cached

    try:
        parsed = fetch_duties(hs_code, origin_numeric)
    except DutiesUnavailable:
        cache.set(key, "unavailable", CALC_NEGATIVE_CACHE_TTL)
        raise

    result = {**parsed, "fetched_at": timezone.now().isoformat(), "source_url": TARIF_CALC_URL}
    cache.set(key, result, CALC_CACHE_TTL)
    return result
