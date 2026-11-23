"""Источник «ЦБ» для банков: файл «Филиалы коммерческих банков» ЦБ РУз (Х-12; исследование 2026-11-11 «Справочники» B1).

Файл xlsx с кодами филиалов (МФО, пять цифр) и названиями; по листу на язык. Адрес файла содержит случайную часть и
меняется, поэтому в настройке `CBU_BANKS_URL` — адрес страницы ЦБ: ссылка на xlsx берётся с неё (прямой адрес файла тоже
подходит). Загрузка только ДОБАВЛЯЕТ новые коды и обновляет названия существующих, кроме полей, изменённых руками.
Код, которого нет в последнем файле, не удаляется: `in_source = False` (факт «нет в последнем файле ЦБ», дата — в
`synced_at` последнего прогона, где код был). Предохранитель: файл короче `MIN_CODES` строк не помечает пропавших.
Прогон идемпотентен; итог — в лог и в журнал (`ActivityLog`), сбой — тоже.
"""

import io
import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urljoin

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .cbu import SOURCE
from .models import Bank

logger = logging.getLogger(__name__)

#: В файле ЦБ ~324 кода; заметно меньше — обрезанный файл, а не закрытие банков.
MIN_CODES = 200
MAX_FILE_BYTES = 20 * 1024 * 1024
_XLSX_LINK = re.compile(r"""href=["']([^"']+\.xlsx)["']""", re.IGNORECASE)
_CODE = re.compile(r"\d{5}")
JOURNAL_ENTITY = "bank_directory"


class BankFileError(Exception):
    """Файл ЦБ не скачался или не читается; текст — для журнала и логов, без секретов."""


@dataclass(frozen=True)
class BankRow:
    code: str
    name_ru: str
    name_uz: str
    name_en: str


@dataclass(frozen=True)
class BankSyncSummary:
    added: int
    updated: int
    missing: int
    total: int

    def text(self) -> str:
        return f"в файле {self.total}; добавлено {self.added}, названия обновлены у {self.updated}, нет в файле {self.missing}"


# ── Файл ─────────────────────────────────────────────────────────────────────────────────────────


def fetch_file(url: Optional[str] = None, *, timeout: int = 60) -> bytes:
    """xlsx со страницы ЦБ (или по прямому адресу). Любой сбой — `BankFileError` с понятным текстом."""
    import httpx

    url = (url or getattr(settings, "CBU_BANKS_URL", "")).strip()
    if not url:
        raise BankFileError("не задан адрес файла ЦБ (CBU_BANKS_URL)")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; directory-sync)"}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            first = client.get(url)
            first.raise_for_status()
            content = first.content
            if not content.startswith(b"PK"):  # страница, а не файл: ищем ссылку на xlsx
                links = _XLSX_LINK.findall(first.text)
                if not links:
                    raise BankFileError("на странице ЦБ нет ссылки на файл xlsx")
                link = next((x for x in links if "filial" in x.lower()), links[0])
                second = client.get(urljoin(str(first.url), link))
                second.raise_for_status()
                content = second.content
    except httpx.HTTPError as exc:
        raise BankFileError(f"ЦБ недоступен: {exc.__class__.__name__}") from exc
    if len(content) > MAX_FILE_BYTES or not content.startswith(b"PK"):
        raise BankFileError("ответ ЦБ не похож на файл xlsx")
    return content


def _language(title: str) -> Optional[str]:
    """Лист по названию: «Русский», «English», узбекский латиницей («O'zbekcha»); кириллический узбекский пропускаем."""
    lowered = title.lower()
    if "рус" in lowered:
        return "ru"
    if "english" in lowered or lowered.startswith("en"):
        return "en"
    if "zbek" in lowered:
        return "uz"
    return None


def _label(bank: str, branch: str) -> str:
    """Название строки: название филиала; если банка в нём не видно — «банк, филиал»."""
    bank, branch = bank.strip(), branch.strip()
    if not branch:
        return bank
    return branch if bank.upper() in branch.upper() or not bank else f"{bank}, {branch}"


def parse(content: bytes) -> list[BankRow]:
    """Строки файла: код — пять цифр в первом столбце, банк и филиал — третий и четвёртый; названия по языкам листов."""
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 — любой битый файл — сбой источника
        raise BankFileError("файл ЦБ не читается как xlsx") from exc
    names: dict[str, dict[str, str]] = {}
    for sheet in workbook.worksheets:
        language = _language(sheet.title)
        if language is None:
            continue
        for raw in sheet.iter_rows(values_only=True):
            code = str(raw[0]).strip() if raw and raw[0] is not None else ""
            if not _CODE.fullmatch(code) or len(raw) < 4:
                continue
            names.setdefault(code, {})[language] = _label(str(raw[2] or ""), str(raw[3] or ""))[:255]
    rows = []
    for code, by_language in names.items():
        fallback = by_language.get("uz") or by_language.get("ru") or by_language.get("en") or ""
        if not fallback:
            continue
        rows.append(
            BankRow(
                code=code,
                name_ru=by_language.get("ru") or fallback,
                name_uz=by_language.get("uz") or fallback,
                name_en=by_language.get("en") or fallback,
            )
        )
    return rows


# ── Запись ───────────────────────────────────────────────────────────────────────────────────────


def sync_banks(rows: Iterable[BankRow], *, now=None) -> BankSyncSummary:
    """Обновить справочник банков по строкам файла одной транзакцией. Ничего не удаляет."""
    rows = list(rows)
    moment = now or timezone.now()
    added = updated = missing = 0
    with transaction.atomic():
        existing = {b.code: b for b in Bank.objects.select_for_update()}
        position = max((b.sort_order for b in existing.values()), default=0)
        for row in rows:
            values = {"name": row.name_ru, "name_uz": row.name_uz, "name_en": row.name_en}
            current = existing.get(row.code)
            if current is None:
                position += 10
                Bank.objects.create(
                    code=row.code,
                    sort_order=position,
                    source=SOURCE,
                    synced_at=moment,
                    in_source=True,
                    **values,
                )
                added += 1
                continue
            manual = set(current.manual_fields or [])
            changed = [f for f, v in values.items() if v and f not in manual and getattr(current, f) != v]
            for field in changed:
                setattr(current, field, values[field])
            current.source, current.synced_at, current.in_source = SOURCE, moment, True
            current.save(update_fields=[*changed, "source", "synced_at", "in_source"])
            updated += bool(changed)
        if len(rows) >= MIN_CODES:
            gone = Bank.objects.filter(source=SOURCE, in_source=True).exclude(code__in=[r.code for r in rows])
            for bank in gone:
                bank.in_source = False
                bank.save(update_fields=["in_source"])
                missing += 1
        elif rows:
            logger.warning("CBU banks: only %s codes in the file — missing ones are not marked", len(rows))
    return BankSyncSummary(added=added, updated=updated, missing=missing, total=len(rows))


def _journal(action: str, detail: str, *, level: str = "INFO") -> None:
    from core.audit import log_admin_action

    try:
        log_admin_action(entity_type=JOURNAL_ENTITY, entity_id=0, action=action, detail=detail, level=level)
    except Exception:  # noqa: BLE001 — журнал не должен ронять загрузку
        logger.warning("CBU banks: cannot write the journal entry", exc_info=True)


def refresh_banks(content: Optional[bytes] = None) -> BankSyncSummary:
    """Скачать (или взять готовый) файл ЦБ, разобрать, обновить справочник; итог или сбой — в лог и журнал.

    Сбой скачивания или разбора пробрасывается `BankFileError` — справочник при этом не меняется."""
    try:
        rows = parse(content if content is not None else fetch_file())
        if not rows:
            raise BankFileError("в файле ЦБ нет ни одного кода банка")
    except BankFileError as exc:
        logger.error("CBU banks: directory not updated — %s", exc)
        _journal("Справочник банков не обновлён", str(exc), level="WARNING")
        raise
    summary = sync_banks(rows)
    logger.info("CBU banks: %s", summary.text())
    _journal("Справочник банков обновлён из файла ЦБ", summary.text())
    return summary
