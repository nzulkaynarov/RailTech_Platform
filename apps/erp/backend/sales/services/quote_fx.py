"""Курс на дату КП (M1-ERP-08): снимок курсов, их фиксация и договорной курс финансиста.

Паттерн — курс документа (Odoo `currency_rate` на заказе, SAP B1 document rate, ERPNext
`conversion_rate` на Quotation): курс хранится на самом КП, позже изменившийся курс ЦБ не трогает
отправленное КП, его PDF, публичную страницу, акцепт и счёт из него.

Правила (по рекомендации, DECISIONS 2026-10-14 M1-ERP-08):

* **Черновик живёт по текущему курсу.** Пока КП в статусе «Черновик» и не отправлено, каждый
  пересчёт берёт курс на сегодня (`finance.services.fx.resolve_rate`) и обновляет снимок — менеджер
  видит экономику по сегодняшнему курсу, а не по курсу дня создания черновика.
* **Фиксация — при отправке на согласование** (`fix_quote_rates`, выход из черновика): согласующий
  видит ровно те суммы, что уйдут клиенту, а отправка ничего не пересчитывает. С этого момента
  пересчёт берёт курсы только из снимка (`fx_fixed_at` — момент фиксации). Возврат КП в черновик
  (отзыв, отклонение шага) снова делает курс живым. Новая версия КП (копия) — новый черновик со
  свежим курсом.
* **Курса нет** — нет строки справочника на дату КП не старше `FX_RATE_MAX_AGE_DAYS` (7 дней):
  валюта попадает в `fx_missing`, отправка на согласование, PDF и отправка клиенту блокируются
  кодом `FX_RATE_MISSING`; выход — обновление курсов ЦБ или договорной курс финансиста.
* **Договорной курс** (`fx_manual`) — только с правом `finance.rates`, с причиной, в журнал; побеждает
  снимок; задаётся и снимается **только в черновике** (FIX-41): на согласовании и позже — 409
  `QUOTE_NOT_DRAFT` (отправленное клиенту — `QUOTE_FROZEN`); путь — вернуть КП в черновик (отзыв),
  поменять курс и отправить на согласование заново.
"""

from decimal import Decimal
from typing import Iterable, Optional

from django.db import transaction
from django.utils import timezone
from finance.services.fx import (
    BASE_CURRENCY,
    RateSource,
    is_base,
    normalize_code,
    parse_positive_rate,
    rate_to_str,
    resolve_rate,
)

from crm.constants import QuoteStatusCode

OVERRIDE_REASON_MAX_LEN = 500
# 12 знаков до запятой и 6 после — как `ExchangeRate.rate_to_uzs` (max_digits=18, decimal_places=6).
_RATE_MAX = Decimal("999999999999.999999")


class QuoteFxError(ValueError):
    """Ошибка курса КП; `str(exc)` — код API (`{"detail": "<CODE>"}`)."""


def _dict(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def rates_are_live(quote) -> bool:
    """Курс черновика живой: КП не отправлено и в статусе «Черновик» (или ещё без статуса)."""
    if quote.frozen_at is not None:
        return False
    status = quote.status if quote.status_id else None
    return status is None or status.code == QuoteStatusCode.DRAFT


def quote_rate_date(quote):
    """Дата, на которую КП берёт курс: живой черновик — сегодня; иначе — день фиксации/отправки."""
    if rates_are_live(quote):
        return timezone.localdate()
    fixed = quote.fx_fixed_at or quote.frozen_at
    return timezone.localdate(fixed) if fixed else timezone.localdate()


def line_currency_codes(items: Iterable) -> set:
    """Валюты себестоимости строк КП (без UZS)."""
    codes = {normalize_code(item.frozen_currency.code if item.frozen_currency_id else None) for item in items}
    codes.discard(BASE_CURRENCY)
    return codes


def resolve_quote_rate_map(quote, codes: Iterable[str]) -> dict:
    """{код: курс} для пересчёта КП; обновляет снимок (`fx_snapshot` + `fx_snapshot_meta`) в памяти.

    Живой черновик: снимок пересобирается по курсу на сегодня (только валюты строк). Зафиксированное
    КП: курс из снимка; валюта, которой в снимке нет (строку добавили после фиксации), берётся на
    дату фиксации и дописывается. Курса нет — в карте 1 (заглушка, чтобы пересчёт не падал), в снимок
    не попадает — `fx_missing` блокирует согласование и отправку. Договорной курс побеждает снимок.
    Вызывающий сохраняет `fx_snapshot`, `fx_snapshot_meta`, `fx_fixed_at`.
    """
    live = rates_are_live(quote)
    on_date = quote_rate_date(quote)
    old_snapshot, old_meta = _dict(quote.fx_snapshot), _dict(quote.fx_snapshot_meta)
    snapshot, meta = ({}, {}) if live else (old_snapshot, old_meta)
    manual = _dict(quote.fx_manual)
    rate_map = {BASE_CURRENCY: Decimal("1")}
    for code in {normalize_code(c) for c in codes} - {BASE_CURRENCY}:
        frozen = None if live else parse_positive_rate(snapshot.get(code))
        if frozen is None:
            resolved = resolve_rate(code, on_date)
            if resolved is not None:
                frozen = resolved.rate
                snapshot[code] = rate_to_str(resolved.rate)
                meta[code] = {"rate_date": resolved.rate_date.isoformat(), "source": resolved.source}
        rate_map[code] = parse_positive_rate(manual.get(code)) or frozen or Decimal("1")
    quote.fx_snapshot, quote.fx_snapshot_meta = snapshot, meta
    if live:
        quote.fx_fixed_at = None
    return rate_map


def live_rates_outdated(quote) -> bool:
    """Живой черновик со снимком не на сегодняшний курс (курс ЦБ обновился после последнего пересчёта).

    Перед отправкой на согласование такой черновик пересчитывается; КП без валютных строк и
    зафиксированное КП не трогаются.
    """
    if not rates_are_live(quote):
        return False
    snapshot, meta = _dict(quote.fx_snapshot), _dict(quote.fx_snapshot_meta)
    today = timezone.localdate()
    for code in line_currency_codes(quote.items.select_related("frozen_currency")):
        resolved = resolve_rate(code, today)
        current = (rate_to_str(resolved.rate), resolved.rate_date.isoformat()) if resolved else None
        stored = (snapshot[code], _dict(meta.get(code)).get("rate_date")) if code in snapshot else None
        if current != stored:
            return True
    return False


def missing_quote_currencies(quote, codes: Iterable[str]) -> list:
    """Валюты строк без курса: ни договорного, ни в снимке, ни в справочнике на дату КП."""
    manual, snapshot = _dict(quote.fx_manual), _dict(quote.fx_snapshot)
    on_date = quote_rate_date(quote)
    missing = []
    for code in sorted({normalize_code(c) for c in codes} - {BASE_CURRENCY}):
        if parse_positive_rate(manual.get(code)) or parse_positive_rate(snapshot.get(code)):
            continue
        if resolve_rate(code, on_date) is None:
            missing.append(code)
    return missing


def quote_fx_rates(quote, codes: Optional[Iterable[str]] = None) -> list:
    """Курсы КП для показа «Курс на <дата>: 1 USD = … UZS (источник)», по валюте.

    Валюты — снимок ∪ договорные ∪ `codes` (валюты строк, когда известны). Только чтение JSON КП —
    без запросов к базе (поле отдаётся и в списках сделок).
    """
    snapshot, meta = _dict(quote.fx_snapshot), _dict(quote.fx_snapshot_meta)
    manual, manual_meta = _dict(quote.fx_manual), _dict(quote.fx_manual_meta)
    all_codes = set(snapshot) | set(manual) | {normalize_code(c) for c in (codes or [])}
    rows = []
    for code in sorted(all_codes - {BASE_CURRENCY}):
        snap_rate = parse_positive_rate(snapshot.get(code))
        snap_meta = _dict(meta.get(code))
        override_rate = parse_positive_rate(manual.get(code))
        override = None
        if override_rate is not None:
            info = _dict(manual_meta.get(code))
            override = {
                "rate": rate_to_str(override_rate),
                "reason": info.get("reason", ""),
                "set_by_name": info.get("set_by_name", ""),
                "set_at": info.get("set_at"),
            }
        effective = override_rate or snap_rate
        if override_rate is not None:
            rate_date = (override["set_at"] or "")[:10] or None
            source = RateSource.OVERRIDE
        else:
            rate_date, source = snap_meta.get("rate_date"), snap_meta.get("source")
        rows.append(
            {
                "currency": code,
                "rate": rate_to_str(effective) if effective else None,
                "rate_date": rate_date,
                "source": source,
                "snapshot_rate": rate_to_str(snap_rate) if snap_rate else None,
                "snapshot_rate_date": snap_meta.get("rate_date"),
                "snapshot_source": snap_meta.get("source"),
                "override": override,
                "missing": effective is None,
            }
        )
    return rows


def fix_quote_rates(quote, actor) -> None:
    """Зафиксировать курсы КП (вызывается при выходе из черновика — отправке на согласование).

    Курсы к этому моменту уже пересчитаны на сегодня (живой черновик); фиксация только ставит
    `fx_fixed_at`, после чего пересчёт перестаёт трогать снимок. Пишет событие в журнал КП.
    """
    from crm.services.quotes._shared import _log_quote

    quote.refresh_from_db(fields=["fx_snapshot", "fx_snapshot_meta", "fx_manual", "fx_manual_meta"])
    quote.fx_fixed_at = timezone.now()
    quote.save(update_fields=["fx_fixed_at", "updated_at"])
    rates = [row for row in quote_fx_rates(quote) if row["rate"]]
    if not rates:
        return
    summary = ", ".join(f"1 {row['currency']} = {row['rate']} UZS" for row in rates)
    _log_quote(
        quote,
        actor,
        "Курсы КП зафиксированы",
        f"КП v{quote.version}: {summary}",
        event_code="quote.fx_fixed",
        event_params={"version": quote.version, "rates": summary},
    )


def _validated_rate(rate) -> Optional[Decimal]:
    if rate in (None, ""):
        return None
    parsed = parse_positive_rate(rate)
    if parsed is None:
        try:
            Decimal(str(rate))
        except ArithmeticError:
            raise QuoteFxError("FX_RATE_INVALID")
        raise QuoteFxError("FX_RATE_MUST_BE_POSITIVE")
    if parsed > _RATE_MAX or parsed != parsed.quantize(Decimal("0.000001")):
        raise QuoteFxError("FX_RATE_INVALID")
    return parsed


def _validated_currency(currency) -> str:
    from core.models import Currency

    code = normalize_code(currency)
    if not (currency or "").strip():
        raise QuoteFxError("FX_CURRENCY_REQUIRED")
    if is_base(code):
        raise QuoteFxError("FX_BASE_CURRENCY")
    if not Currency.objects.filter(code=code, is_active=True).exists():
        raise QuoteFxError("FX_CURRENCY_UNKNOWN")
    return code


def _actor_name(actor) -> str:
    full = f"{getattr(actor, 'first_name', '')} {getattr(actor, 'last_name', '')}".strip()
    return full or getattr(actor, "email", "") or ""


def set_quote_rate_override(quote_id: int, *, actor, currency: str, rate, reason: str):
    """Договорной курс КП (`rate`) или его снятие (`rate=None`) — с причиной, в журнал (`finance.rates`).

    Ошибки — `QuoteFxError` с кодом: ROLE_NOT_PERMITTED, QUOTE_FROZEN, QUOTE_NOT_DRAFT, FX_CURRENCY_REQUIRED,
    FX_BASE_CURRENCY, FX_CURRENCY_UNKNOWN, FX_RATE_INVALID, FX_RATE_MUST_BE_POSITIVE,
    FX_OVERRIDE_REASON_REQUIRED, FX_OVERRIDE_REASON_TOO_LONG. Снятие несуществующего курса — no-op.
    """
    from accounts.services.permissions import can_manage_quote_rates
    from crm.models import Quote

    if not can_manage_quote_rates(actor):
        raise QuoteFxError("ROLE_NOT_PERMITTED")
    code = _validated_currency(currency)
    new_rate = _validated_rate(rate)
    reason = (reason or "").strip()
    if not reason:
        raise QuoteFxError("FX_OVERRIDE_REASON_REQUIRED")
    if len(reason) > OVERRIDE_REASON_MAX_LEN:
        raise QuoteFxError("FX_OVERRIDE_REASON_TOO_LONG")
    with transaction.atomic():
        quote = Quote.objects.select_for_update(of=("self",)).select_related("deal").get(pk=quote_id)
        if quote.frozen_at is not None:
            raise QuoteFxError("QUOTE_FROZEN")
        if not rates_are_live(quote):
            # Договорной курс меняет цену КП: на согласовании и позже — только через возврат в черновик
            # и повторное согласование (FIX-41, F-2).
            raise QuoteFxError("QUOTE_NOT_DRAFT")
        manual, manual_meta = _dict(quote.fx_manual), _dict(quote.fx_manual_meta)
        previous = manual.get(code)
        if new_rate is None and previous is None:
            return quote
        if new_rate is None:
            manual.pop(code, None)
            manual_meta.pop(code, None)
        else:
            manual[code] = rate_to_str(new_rate)
            manual_meta[code] = {
                "reason": reason,
                "set_by": actor.pk,
                "set_by_name": _actor_name(actor),
                "set_at": timezone.localtime().isoformat(),
            }
        quote.fx_manual, quote.fx_manual_meta = manual, manual_meta
        quote.save(update_fields=["fx_manual", "fx_manual_meta", "updated_at"])
        _log_override(quote, actor, code, previous, manual.get(code), reason)
        from crm.services import QuoteCalculationService

        QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()
    return quote


def _log_override(quote, actor, code, previous, current, reason) -> None:
    from core.audit import log_admin_action

    cleared = current is None
    log_admin_action(
        entity_type="quote",
        entity_id=quote.pk,
        action="Договорной курс КП снят" if cleared else "Договорной курс КП задан",
        detail=f"КП v{quote.version}: 1 {code} = {current or '—'} UZS (было {previous or 'курс ЦБ'})",
        actor=actor,
        reason=reason,
        before={"currency": code, "rate": previous},
        after={"currency": code, "rate": current},
        deal_id=quote.deal_id,
        company_id=quote.deal.company_id if quote.deal_id else None,
        event_code="quote.fx_override_cleared" if cleared else "quote.fx_overridden",
        event_params={
            "version": quote.version,
            "currency": code,
            "rate": current or "",
            "previous": previous or "",
            "reason": reason,
        },
    )
