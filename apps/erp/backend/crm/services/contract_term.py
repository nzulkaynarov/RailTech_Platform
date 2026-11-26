"""ДС-1: срок договора (решение владельца 2026-11-25) — вычисляется при подписании, продлевается ночной задачей.

Что здесь решается фактами, а не кодом:

* срок, тип продления и срок отказа — правило компании (`CompanySettings.contract_*`), которое шаблон договора может
  переопределить (`DocumentTemplate.term_rule|renewal_mode|notice_days`); арифметика дат — `core/contract_term.py`;
* срок считается в момент подписания (скан приложен, статус «Подписан»), хранится на договоре вместе с редакцией шаблона;
  дату окончания и «последний день отказа» вручную не вводят;
* ночная задача (`crm.run_contract_terms`): продлевает договор с типом «сам» (журнал + уведомление контрагенту в Кабинете),
  напоминает ответственному за N дней до последнего дня отказа (по одному разу на метку), иностранному контрагенту —
  за `foreign_remind_days` до конца срока вместо автопродления (продление — доп. соглашением, действие `renew`);
* после окончания срока блокируются только НОВЫЕ КП и сделки с контрагентом (или предупреждают — настройка);
  начатая работа, оплаты, акты и претензии не зависят от срока никогда (ГК РУз ст. 357);
* новая редакция шаблона действует для контрагента только после его подписи: пока он не подписал, договор продлевается
  на старой редакции; отправить новую — одним действием (`send_new_edition`).
"""

import datetime as dt
import logging
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from core.contract_term import ContractRenewalMode, ContractTermRule, DeclinedBy, first_term, next_term, term_from_today

from ..constants import ContractStatusCode
from ..models import ActivityLog, Contract

logger = logging.getLogger(__name__)

EXPIRED_CODE = "COUNTERPARTY_CONTRACT_EXPIRED"


# ── Правила: компания + шаблон ─────────────────────────────────────────────────────────────────────────────────────


def is_foreign(company, seller_company=None) -> bool:
    """Нерезидент: страна контрагента и страна компании указаны и различаются. Страны нет — как у резидента."""
    from core.tenant import own_company

    seller = seller_company or own_company()
    theirs = getattr(company, "country_id", None)
    ours = getattr(seller, "country_id", None)
    return bool(theirs and ours and theirs != ours)


def term_rules(seller_company, template, counterparty) -> dict:
    """Правила срока для договора: настройка компании, поверх — поля шаблона; иностранный — продление соглашением."""
    from .contract_templates import contract_rules

    base = contract_rules(seller_company)
    rule = (template.term_rule if template is not None else "") or base["term_rule"]
    notice_days = (
        template.notice_days if template is not None and template.notice_days is not None else base["notice_days"]
    )
    mode = (template.renewal_mode if template is not None else "") or (
        ContractRenewalMode.AUTO if base["auto_renew"] else ContractRenewalMode.NONE
    )
    foreign = is_foreign(counterparty, seller_company)
    if foreign and base["foreign_by_agreement"] and mode == ContractRenewalMode.AUTO:
        mode = ContractRenewalMode.BY_AGREEMENT
    if rule == ContractTermRule.OPEN:
        mode = ContractRenewalMode.NONE
    return {
        "rule": rule,
        "mode": mode,
        "notice_days": notice_days,
        "boundary_day": base["next_year_from_day"],
        "remind_first": base["remind_first_days"],
        "remind_last": base["remind_last_days"],
        "foreign_remind": base["foreign_remind_days"],
        "expired_action": base["expired_action"],
        "foreign": foreign,
    }


def _seller(contract):
    from .contract_templates import _own_seller

    return _own_seller(contract)


def _rules_of(contract) -> dict:
    return term_rules(_seller(contract), contract.template, contract.deal.company)


def _journal(contract, event_code: str, action: str, *, actor=None, contact=None, level="INFO", **params):
    return ActivityLog.objects.create(
        action=action,
        detail=f"Договор {contract.number} / сделка #{contract.deal_id}",
        event_code=event_code,
        event_params={"number": contract.number, "deal_id": contract.deal_id, **params},
        user=actor,
        contact=contact,
        level=level,
        entity_type="contract",
        entity_id=contract.id,
        deal=contract.deal,
        company_id=contract.deal.company_id,
    )


# ── Подписание ─────────────────────────────────────────────────────────────────────────────────────────────────────


def compute_term(seller_company, template, counterparty, signed_on: dt.date) -> tuple:
    """Правила компании и первый срок для договора, подписанного `signed_on`: `(rules, Term)`.

    Единственное место, где срок вычисляется из правила: договор клиента (`apply_at_signing`), договор партнёра
    (`apply_to_partner_application`) и дозаполнение прежних договоров (`backfill_contract_terms`)."""
    rules = term_rules(seller_company, template, counterparty)
    term = first_term(signed_on, rules["rule"], notice_days=rules["notice_days"], boundary_day=rules["boundary_day"])
    return rules, term


@transaction.atomic
def apply_to_partner_application(app, *, signed_on: Optional[dt.date] = None) -> None:
    """ПК-1: договор партнёра отмечен «подписан» — срок по тому же правилу, что у клиентов. Повтор — без изменений."""
    if app.contract_valid_until is not None or app.contract_term_rule:
        return
    from core.tenant import own_company

    signed_on = signed_on or timezone.localdate()
    counterparty = app.company
    rules, term = compute_term(own_company(), app.contract_template, counterparty, signed_on)
    app.contract_valid_from = term.valid_from
    app.contract_valid_until = term.valid_until
    app.contract_last_notice_date = term.last_notice_date
    app.contract_term_rule = rules["rule"]
    app.contract_renewal_mode = rules["mode"]
    app.contract_notice_days = rules["notice_days"]


def apply_to_package(app, *, signed_on: Optional[dt.date] = None) -> None:
    """ОСН-1: документы пакета кандидата получают срок в тот же момент отметки «подписан».

    Договор о партнёрстве и оферта — по правилу компании (тот же `compute_term`); NDA срока договора не имеет, он хранит
    свои поля шаблона: «тайна после окончания, лет» и «без срока». Повтор — без изменений."""
    from core.tenant import own_company

    signed_on = signed_on or timezone.localdate()
    for row in app.package_documents.select_related("template"):
        if row.valid_from is not None:
            continue
        row.valid_from = signed_on
        if row.base_role == "nda":
            row.confidentiality_years = row.template.confidentiality_years if row.template_id else None
            row.trade_secret_indefinite = bool(row.template_id and row.template.trade_secret_indefinite)
        else:
            _, term = compute_term(own_company(), row.template, app.company, signed_on)
            row.valid_from = term.valid_from
            row.valid_until = term.valid_until
        row.save()


@transaction.atomic
def apply_at_signing(contract, *, signed_on: Optional[dt.date] = None) -> None:
    """Договор подписан: вычислить срок из правила и записать на договор. Повтор — без изменений (срок уже стоит)."""
    if contract.valid_until is not None or contract.term_rule:
        return
    signed_on = signed_on or timezone.localdate()
    rules, term = compute_term(_seller(contract), contract.template, contract.deal.company, signed_on)
    contract.valid_from = term.valid_from
    contract.valid_until = term.valid_until
    contract.last_notice_date = term.last_notice_date
    contract.term_rule = rules["rule"]
    contract.renewal_mode = rules["mode"]
    contract.notice_days = rules["notice_days"]
    contract.term_foreign = rules["foreign"]
    contract.save(
        update_fields=[
            "valid_from",
            "valid_until",
            "last_notice_date",
            "term_rule",
            "renewal_mode",
            "notice_days",
            "term_foreign",
            "updated_at",
        ]
    )
    _journal(
        contract,
        "contract.term_set",
        "Определён срок договора",
        valid_until=str(term.valid_until or ""),
        last_notice_date=str(term.last_notice_date or ""),
        rule=rules["rule"],
        renewal=rules["mode"],
        template_edition=contract.template_edition,
    )
    if contract.supersedes_id:
        _close_superseded(contract)


def _close_superseded(contract) -> None:
    """Новая редакция подписана: прежний договор заканчивается накануне, продлеваться ему больше не нужно."""
    old = Contract.objects.select_for_update().get(pk=contract.supersedes_id)
    if old.valid_until is None or old.valid_until >= contract.valid_from:
        old.valid_until = contract.valid_from - dt.timedelta(days=1)
    old.renewal_mode = ContractRenewalMode.NONE
    old.last_notice_date = None
    old.save(update_fields=["valid_until", "renewal_mode", "last_notice_date", "updated_at"])
    _journal(
        old,
        "contract.superseded",
        "Договор заменён новой редакцией",
        new_number=contract.number,
        new_edition=contract.template_edition,
    )


# ── Отказ от продления и ручное продление ──────────────────────────────────────────────────────────────────────────


def _locked(contract_id: int):
    return (
        Contract.objects.select_for_update(of=("self",))
        .select_related("deal__company", "quote", "status", "template")
        .filter(pk=contract_id)
        .first()
    )


@transaction.atomic
def decline_renewal(
    contract_id: int, side: str, *, actor=None, contact=None, today: Optional[dt.date] = None
) -> Tuple[Optional[Contract], Optional[str]]:
    """«Отказаться от продления»: договор доживёт до конца срока и закончится. Можно до последнего дня отказа."""
    from .contract_flow import is_staff, may

    today = today or timezone.localdate()
    if side == DeclinedBy.COMPANY and not (is_staff(actor) and may(actor, "contract.manage")):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    contract = _locked(contract_id)
    if contract is None:
        return None, "CONTRACT_NOT_FOUND"
    if contract.status_code != ContractStatusCode.SIGNED or contract.valid_until is None:
        return None, "TERM_NOT_SET"
    if contract.renewal_declined_at is not None:
        return None, "TERM_ALREADY_DECLINED"
    if contract.renewal_mode != ContractRenewalMode.AUTO:
        return None, "TERM_NOT_AUTO_RENEWING"
    if contract.last_notice_date is None or today > contract.last_notice_date:
        return None, "TERM_NOTICE_PASSED"
    contract.renewal_declined_at = timezone.now()
    contract.renewal_declined_by = side
    contract.save(update_fields=["renewal_declined_at", "renewal_declined_by", "updated_at"])
    _journal(
        contract,
        "contract.renewal_declined",
        "Отказ от продления договора",
        actor=actor,
        contact=contact,
        by=side,
        valid_until=str(contract.valid_until),
    )
    transaction.on_commit(lambda: _notify_declined(contract.pk, side))
    return contract, None


@transaction.atomic
def restore_renewal(
    contract_id: int, side: str, *, actor=None, contact=None, today: Optional[dt.date] = None
) -> Tuple[Optional[Contract], Optional[str]]:
    """Вернуть продление: свой отказ можно снять в любой день до последнего дня отказа (не только в окне «Продлить»)."""
    from .contract_flow import is_staff, may

    today = today or timezone.localdate()
    if side == DeclinedBy.COMPANY and not (is_staff(actor) and may(actor, "contract.manage")):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    contract = _locked(contract_id)
    if contract is None:
        return None, "CONTRACT_NOT_FOUND"
    if contract.status_code != ContractStatusCode.SIGNED or contract.valid_until is None:
        return None, "TERM_NOT_SET"
    if contract.renewal_declined_at is None or contract.renewal_declined_by != side:
        return None, "TERM_NOT_DECLINED"
    if contract.last_notice_date is None or today > contract.last_notice_date:
        return None, "TERM_NOTICE_PASSED"
    contract.renewal_declined_at = None
    contract.renewal_declined_by = ""
    contract.term_reminders = []
    contract.save(update_fields=["renewal_declined_at", "renewal_declined_by", "term_reminders", "updated_at"])
    _journal(
        contract,
        "contract.renewal_restored",
        "Отказ от продления снят",
        actor=actor,
        contact=contact,
        by=side,
        valid_until=str(contract.valid_until),
    )
    return contract, None


@transaction.atomic
def renew_by_agreement(
    contract_id: int, actor, *, agreement_number: str = "", today: Optional[dt.date] = None
) -> Tuple[Optional[Contract], Optional[str]]:
    """Продление по соглашению сторон (иностранный контрагент, истёкший договор): новый срок, отказ снимается."""
    from .contract_flow import is_staff, may

    today = today or timezone.localdate()
    if not (is_staff(actor) and may(actor, "contract.manage")):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    contract = _locked(contract_id)
    if contract is None:
        return None, "CONTRACT_NOT_FOUND"
    if contract.status_code != ContractStatusCode.SIGNED or contract.valid_until is None:
        return None, "TERM_NOT_SET"
    rules = _rules_of(contract)
    if not can_renew(contract, rules, today):
        return None, "TERM_ALREADY_RENEWED"
    rule = contract.term_rule or rules["rule"]
    notice = contract.notice_days
    if contract.valid_until >= today:
        term = next_term(contract.valid_until, rule, notice_days=notice, today=today)
    else:
        term = term_from_today(today, rule, notice_days=notice, boundary_day=rules["boundary_day"])
    _apply_renewal(contract, term)
    contract.renewal_declined_at = None
    contract.renewal_declined_by = ""
    contract.save(update_fields=["renewal_declined_at", "renewal_declined_by", "updated_at"])
    _journal(
        contract,
        "contract.term_renewed_by_agreement",
        "Договор продлён по соглашению",
        actor=actor,
        agreement_number=(agreement_number or "").strip()[:64],
        valid_until=str(term.valid_until or ""),
    )
    transaction.on_commit(
        lambda: _notify_renewed_safely(contract.deal.company_id, [contract.pk], str(term.valid_until or ""))
    )
    return contract, None


def can_renew(contract, rules: dict, today: dt.date) -> bool:
    """Продлить по соглашению можно, когда срок вышел или до конца осталось не больше окна напоминания.

    Договор, уже продлённый дальше окна, повторно не продлевается: два нажатия в один день добавляют один срок."""
    if contract.valid_until is None:
        return False
    if contract.valid_until < today:
        return True
    window = rules["foreign_remind"] if contract.renewal_mode != ContractRenewalMode.AUTO else contract.notice_days
    return (contract.valid_until - today).days <= window


def _apply_renewal(contract, term) -> None:
    contract.valid_from = term.valid_from
    contract.valid_until = term.valid_until
    contract.last_notice_date = term.last_notice_date
    contract.renewals_count = (contract.renewals_count or 0) + 1
    contract.term_reminders = []
    contract.save(
        update_fields=[
            "valid_from",
            "valid_until",
            "last_notice_date",
            "renewals_count",
            "term_reminders",
            "updated_at",
        ]
    )


# ── Ночная задача ──────────────────────────────────────────────────────────────────────────────────────────────────


def run_daily(today: Optional[dt.date] = None) -> dict:
    """Продлить, напомнить. Идемпотентна: повтор в тот же день ничего не меняет (срок уже сдвинут, метка напоминания стоит).

    Сбой одного договора или одной компании журналируется и не останавливает остальных (`failed` в ответе). Уведомление о
    продлении повторяемо: пока нет записи «уведомление отправлено» (`contract.term_notice_sent`), следующий запуск
    отправит его снова — падение между продлением и уведомлением не теряет письмо."""
    today = today or timezone.localdate()
    renewed = reminded = failed = 0
    base = Contract.objects.filter(status__code=ContractStatusCode.SIGNED, valid_until__isnull=False)
    for pk in list(base.filter(valid_until__lt=today).values_list("pk", flat=True)):
        try:
            if _renew_one(pk, today) is not None:
                renewed += 1
        except Exception:  # noqa: BLE001 — один договор не останавливает остальных
            failed += 1
            logger.exception("run_contract_terms: договор #%s не продлён", pk)
    failed += _send_pending_notices(today)
    for pk in list(base.filter(valid_until__gte=today).values_list("pk", flat=True)):
        try:
            reminded += _remind_one(pk, today)
        except Exception:  # noqa: BLE001
            failed += 1
            logger.exception("run_contract_terms: напоминание по договору #%s не отправлено", pk)
    return {"renewed": renewed, "reminded": reminded, "failed": failed}


NOTICE_RETRY_DAYS = 30


def _send_pending_notices(today: dt.date) -> int:
    """Отправить уведомления о продлении, которых ещё нет: одно на компанию и новую дату окончания. Возвращает число сбоев."""
    since = timezone.now() - dt.timedelta(days=NOTICE_RETRY_DAYS)
    logs = list(
        ActivityLog.objects.filter(event_code="contract.term_renewed", entity_type="contract", timestamp__gte=since)
        .order_by("pk")
        .values("pk", "entity_id", "event_params")
    )
    if not logs:
        return 0
    sent = set(
        ActivityLog.objects.filter(event_code="contract.term_notice_sent", timestamp__gte=since).values_list(
            "event_params__renewal_log", flat=True
        )
    )
    groups: dict = {}
    for row in logs:
        if row["pk"] in sent:
            continue
        contract = Contract.objects.select_related("deal").filter(pk=row["entity_id"]).first()
        if contract is None:
            continue
        key = (contract.deal.company_id, str(row["event_params"].get("valid_until") or ""))
        groups.setdefault(key, []).append((row["pk"], contract.pk))
    failed = 0
    for (company_id, until), items in groups.items():
        try:
            with transaction.atomic():
                _notify_renewed(company_id, [cid for _, cid in items], until)
                for log_id, cid in items:
                    contract = Contract.objects.select_related("deal").get(pk=cid)
                    _journal(
                        contract, "contract.term_notice_sent", "Контрагенту сообщено о продлении", renewal_log=log_id
                    )
        except Exception:  # noqa: BLE001 — повторим при следующем запуске
            failed += 1
            logger.exception("run_contract_terms: уведомление компании #%s о продлении не отправлено", company_id)
    return failed


@transaction.atomic
def _renew_one(contract_id: int, today: dt.date):
    contract = _locked(contract_id)
    if contract is None or contract.valid_until is None or contract.valid_until >= today:
        return None  # уже продлён параллельным запуском
    if contract.status_code != ContractStatusCode.SIGNED:
        return None
    if contract.renewal_mode != ContractRenewalMode.AUTO or contract.renewal_declined_at is not None:
        return None
    if contract.term_rule == ContractTermRule.OPEN:
        return None
    term = next_term(contract.valid_until, contract.term_rule, notice_days=contract.notice_days, today=today)
    previous = contract.valid_until
    _apply_renewal(contract, term)
    entry = _journal(
        contract,
        "contract.term_renewed",
        "Договор продлён автоматически",
        previous_until=str(previous),
        valid_until=str(term.valid_until),
        template_edition=contract.template_edition,
    )
    return contract.deal.company_id, term.valid_until, entry.pk


def _reminder_plan(contract, rules: dict, today: dt.date):
    """`(метки, самый срочный порог, дата-якорь)` сегодняшних напоминаний или `None`."""
    if contract.renewal_declined_at is not None or contract.renewal_mode == ContractRenewalMode.NONE:
        return None
    if contract.renewal_mode == ContractRenewalMode.AUTO:
        anchor = contract.last_notice_date
        thresholds = sorted({rules["remind_first"], rules["remind_last"]}, reverse=True)
    else:
        anchor = contract.valid_until
        thresholds = [rules["foreign_remind"]]
    if anchor is None or today > anchor:
        return None
    due = [n for n in thresholds if today >= anchor - dt.timedelta(days=n)]
    marks = [f"{n}:{anchor.isoformat()}" for n in due]
    fresh = [m for m in marks if m not in (contract.term_reminders or [])]
    if not fresh:
        return None
    return marks, min(due), anchor


@transaction.atomic
def _remind_one(contract_id: int, today: dt.date) -> int:
    contract = _locked(contract_id)
    if contract is None or contract.status_code != ContractStatusCode.SIGNED or contract.valid_until is None:
        return 0
    plan = _reminder_plan(contract, _rules_of(contract), today)
    if plan is None:
        return 0
    marks, days, anchor = plan
    contract.term_reminders = sorted(set(contract.term_reminders or []) | set(marks))
    contract.save(update_fields=["term_reminders", "updated_at"])
    by_agreement = contract.renewal_mode != ContractRenewalMode.AUTO
    _journal(
        contract,
        "contract.term_reminder",
        "Напоминание о сроке договора",
        level="WARNING",
        days=days,
        anchor=str(anchor),
        by_agreement=by_agreement,
        valid_until=str(contract.valid_until),
    )
    _remind_staff(contract, days, anchor, by_agreement)
    return 1


def _responsible(contract):
    return contract.deal.assigned_to or (contract.quote.prepared_by if contract.quote_id else None)


def _remind_staff(contract, days: int, anchor: dt.date, by_agreement: bool) -> None:
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    user = _responsible(contract)
    if user is None:
        return
    kind = NotificationType.objects.filter(code="WARNING").first()
    if by_agreement:
        message = f"Договор {contract.number} заканчивается {contract.valid_until:%d.%m.%Y}: продлите соглашением."
    else:
        message = (
            f"Договор {contract.number} продлится сам: отказаться можно до {anchor:%d.%m.%Y}, "
            f"сейчас осталось {max((anchor - timezone.localdate()).days, 0)} дн."
        )
    notif = Notification.objects.create(
        user=user,
        type=kind,
        title="Срок договора",
        message=message,
        link="/crm/deals",
        deal=contract.deal,
        event_code="contract.term_reminder",
        event_params={
            "number": contract.number,
            "days": days,
            "anchor": anchor.isoformat(),
            "by_agreement": by_agreement,
        },
    )
    push_notification_ws(notif)


# ── Уведомления контрагенту (Кабинет, письмо) ──────────────────────────────────────────────────────────────────────


def _notify_renewed(company_id: int, contract_ids: list, until: str) -> None:
    from portal.services import notice_sources

    from accounts.models import Company

    company = Company.objects.filter(pk=company_id).first()
    contracts = list(Contract.objects.select_related("template").filter(pk__in=contract_ids).order_by("pk"))
    if company is None or not contracts:
        return
    notice_sources.contract_renewed(contracts, company, until=until)


def _notify_renewed_safely(company_id: int, contract_ids: list, until: str) -> None:
    try:
        _notify_renewed(company_id, contract_ids, until)
    except Exception:  # noqa: BLE001 — договор уже продлён, уведомление не должно ронять ответ
        logger.exception("уведомление о продлении договора %s не отправлено", contract_ids)


def _notify_declined(contract_id: int, side: str) -> None:
    contract = Contract.objects.select_related("deal__company", "quote", "template").filter(pk=contract_id).first()
    if contract is None:
        return
    if side == DeclinedBy.COMPANY:
        from portal.services import notice_sources

        notice_sources.contract_renewal_declined(contract)
        return
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    user = _responsible(contract)
    if user is None:
        return
    notif = Notification.objects.create(
        user=user,
        type=NotificationType.objects.filter(code="WARNING").first(),
        title="Отказ от продления",
        message=f"Контрагент отказался от продления договора {contract.number}: он закончится {contract.valid_until:%d.%m.%Y}.",
        link="/crm/deals",
        deal=contract.deal,
        event_code="contract.renewal_declined",
        event_params={"number": contract.number, "valid_until": str(contract.valid_until)},
    )
    push_notification_ws(notif)


# ── Что происходит после окончания срока ───────────────────────────────────────────────────────────────────────────


def in_force(contract, today: dt.date) -> bool:
    return contract.valid_until is None or contract.valid_until >= today


def gates_new_deals(contract, kinds) -> bool:
    """Договор такого вида ограничивает новые сделки (настройка `contract_gating_kinds`; по умолчанию — никакой)."""
    template = contract.template
    if template is None or not kinds:
        return False
    return (template.counterparty_kind == "partner" and "partner" in kinds) or template.subject in kinds


def expired_state(company, today: Optional[dt.date] = None, kinds=None) -> Optional[dict]:
    """Договоры контрагента, которые ограничивают новые сделки (`kinds`), все закончились: `{contract_id, number, valid_until}`.

    Договор по сделке новое КП не закрывает (возвращающийся клиент получит новый договор по новой сделке): без настройки
    `contract_gating_kinds` ответ всегда `None`. Нет подписанных договоров таких видов — `None`."""
    from core.tenant import own_company

    from .contract_templates import contract_rules

    if company is None:
        return None
    today = today or timezone.localdate()
    if kinds is None:
        kinds = contract_rules(own_company())["gating_kinds"]
    signed = [
        c
        for c in Contract.objects.filter(deal__company=company, status__code=ContractStatusCode.SIGNED)
        .exclude(valid_from__isnull=True)
        .select_related("template")
        .order_by("-valid_until", "-pk")
        if gates_new_deals(c, kinds)
    ]
    if not signed or any(in_force(c, today) for c in signed):
        return None
    last = max(signed, key=lambda c: (c.valid_until or dt.date.min, c.pk))
    return {"contract_id": last.pk, "number": last.number, "valid_until": last.valid_until}


def new_work_error(company, seller_company=None) -> Optional[str]:
    """Код отказа для НОВОЙ работы с контрагентом (КП, сделка); `None` — можно. Начатые сделки эту проверку не зовут."""
    from core.tenant import own_company

    from .contract_templates import contract_rules

    rules = contract_rules(seller_company or own_company())
    if expired_state(company, kinds=rules["gating_kinds"]) is None:
        return None
    action = rules["expired_action"]
    return EXPIRED_CODE if action == "block" else None


def new_document_error(contract, today: Optional[dt.date] = None) -> Optional[str]:
    """Срок ЭТОГО договора вышел: новые документы под ним (допсоглашения, спецификации, счета) — `CONTRACT_TERM_OVER`
    при правиле «не создавать», иначе `None`. Начатые документы и оплаты не зависят от срока."""
    from .contract_templates import contract_rules

    if contract.valid_until is None or in_force(contract, today or timezone.localdate()):
        return None
    return "CONTRACT_TERM_OVER" if contract_rules(_seller(contract))["expired_action"] == "block" else None


# ── Новая редакция шаблона ─────────────────────────────────────────────────────────────────────────────────────────


def newest_edition(template):
    """Самая новая утверждённая редакция шаблона по цепочке `previous_edition`; `None` — своя редакция последняя."""
    from documents.models.documents import DocumentTemplate, TemplateApproval

    if template is None:
        return None
    frontier, best, seen = [template.pk], None, {template.pk}
    while frontier:
        children = DocumentTemplate.objects.filter(previous_edition_id__in=frontier)
        frontier = []
        for child in children:
            if child.pk in seen:
                continue
            seen.add(child.pk)
            frontier.append(child.pk)
            if child.approval_status == TemplateApproval.APPROVED and (best is None or child.edition > best.edition):
                best = child
    return best


def on_old_edition(seller_company, today: Optional[dt.date] = None):
    """Договоры в силе на старой редакции шаблона, для которых есть новая и ещё не отправлена: список для «Права»."""
    today = today or timezone.localdate()
    rows = []
    qs = (
        Contract.objects.filter(
            status__code=ContractStatusCode.SIGNED, template__isnull=False, valid_from__isnull=False
        )
        .select_related("deal__company", "template", "quote")
        .order_by("valid_until", "pk")
    )
    for contract in qs:
        if (
            not in_force(contract, today)
            or contract.renewal_mode == ContractRenewalMode.NONE
            and contract.valid_until is None
        ):
            continue
        newer = newest_edition(contract.template)
        if (
            newer is None
            or Contract.objects.filter(supersedes=contract).exclude(status__code=ContractStatusCode.CANCELLED).exists()
        ):
            continue
        rows.append((contract, newer))
    return rows


@transaction.atomic
def send_new_edition(contract_id: int, actor) -> Tuple[Optional[Contract], Optional[str]]:
    """Одним действием отправить контрагенту новую редакцию шаблона на подпись в Кабинет (новый договор, прежний действует)."""
    from .contract_flow import is_staff, may
    from .contract_templates import sign_by_company, try_auto_send, unfilled_variables
    from .contracts import _initial_contract_wordings, _next_contract_number

    if not (is_staff(actor) and may(actor, "contract.manage")):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    old = _locked(contract_id)
    if old is None:
        return None, "CONTRACT_NOT_FOUND"
    if old.status_code != ContractStatusCode.SIGNED or old.template_id is None:
        return None, "TERM_NOT_SET"
    newer = newest_edition(old.template)
    if newer is None:
        return None, "TERM_NO_NEW_EDITION"
    if Contract.objects.filter(supersedes=old).exclude(status__code=ContractStatusCode.CANCELLED).exists():
        return None, "TERM_NEW_EDITION_ALREADY_SENT"
    from .contract_flow import _status_row

    seller = _seller(old)
    new = Contract.objects.create(
        deal=old.deal,
        quote=old.quote,
        template=newer,
        template_edition=newer.edition,
        frozen_template_body=newer.body_html,
        wording_selections=_initial_contract_wordings(seller),
        number=_next_contract_number(seller),
        status=_status_row(ContractStatusCode.DRAFT),
        total_amount=old.total_amount,
        currency=old.currency,
        created_by=actor,
        supersedes=old,
    )
    missing = unfilled_variables(new, new.frozen_template_body)
    if missing:
        transaction.set_rollback(True)
        return None, "CONTRACT_TEMPLATE_UNFILLED"
    from ..tasks import render_document_pdf

    transaction.on_commit(lambda: render_document_pdf.delay("contract", new.pk))
    _journal(
        old,
        "contract.new_edition_sent",
        "Новая редакция шаблона отправлена на подпись",
        actor=actor,
        new_number=new.number,
        edition=newer.edition,
        old_edition=old.template_edition,
    )
    if may(actor, "contract.sign") and not sign_by_company(new.pk, actor)[1]:
        new.refresh_from_db()
    else:
        try_auto_send(new)
        new.refresh_from_db()
    return new, None


# ── Карточки ───────────────────────────────────────────────────────────────────────────────────────────────────────


def state_of(contract, today: dt.date) -> str:
    """`open` — без срока; `renews` — продлится сам; `ends` — отказ или продление соглашением; `expired` — срок вышел."""
    if contract.valid_until is None:
        return "open"
    if contract.valid_until < today:
        return (
            "expired" if contract.renewal_mode != ContractRenewalMode.AUTO or contract.renewal_declined_at else "renews"
        )
    if contract.renewal_mode == ContractRenewalMode.AUTO and contract.renewal_declined_at is None:
        return "renews"
    return "ends"


def term_card(contract, user=None, today: Optional[dt.date] = None) -> Optional[dict]:
    """Срок подписанного договора для карточек Платформы; `None` — срока ещё нет (не подписан или договор до ДС-1)."""
    from .contract_flow import is_staff, may

    if contract.status_code != ContractStatusCode.SIGNED or contract.valid_from is None:
        return None
    today = today or timezone.localdate()
    template = contract.template
    actions = []
    staff = user is not None and is_staff(user) and may(user, "contract.manage")
    state = state_of(contract, today)
    if staff:
        if (
            contract.renewal_mode == ContractRenewalMode.AUTO
            and contract.renewal_declined_at is None
            and contract.last_notice_date is not None
            and today <= contract.last_notice_date
        ):
            actions.append("decline_renewal")
        if (
            contract.renewal_declined_by == DeclinedBy.COMPANY
            and contract.last_notice_date is not None
            and today <= contract.last_notice_date
        ):
            actions.append("restore_renewal")
        if (state in ("ends", "expired") or contract.renewal_mode == ContractRenewalMode.BY_AGREEMENT) and can_renew(
            contract, _rules_of(contract), today
        ):
            actions.append("renew")
        if (
            newest_edition(template) is not None
            and not Contract.objects.filter(supersedes=contract)
            .exclude(status__code=ContractStatusCode.CANCELLED)
            .exists()
        ):
            actions.append("send_new_edition")
    newer = newest_edition(template)
    return {
        "state": state,
        "rule": contract.term_rule or ContractTermRule.CALENDAR_YEAR,
        "renewal": contract.renewal_mode or ContractRenewalMode.NONE,
        "valid_from": contract.valid_from,
        "valid_until": contract.valid_until,
        "last_notice_date": contract.last_notice_date,
        "notice_days": contract.notice_days,
        "renewals_count": contract.renewals_count,
        "foreign": contract.term_foreign,
        "declined_by": contract.renewal_declined_by or None,
        "declined_at": contract.renewal_declined_at,
        "template_edition": contract.template_edition,
        "newer_edition": newer.edition if newer is not None else None,
        "confidentiality_years": template.confidentiality_years if template is not None else None,
        "trade_secret_indefinite": bool(template.trade_secret_indefinite) if template is not None else False,
        "actions": actions,
    }


def counterparty_term(company, today: Optional[dt.date] = None) -> Optional[dict]:
    """Срок договоров в карточке контрагента: действующий (или последний) договор и что с новой работой."""
    today = today or timezone.localdate()
    signed = list(
        Contract.objects.filter(deal__company=company, status__code=ContractStatusCode.SIGNED)
        .exclude(valid_from__isnull=True)
        .select_related("deal", "template")
    )
    if not signed:
        return None
    live = [c for c in signed if in_force(c, today)]
    pick = max(live or signed, key=lambda c: (c.valid_until or dt.date.max, c.pk))
    expired = not live
    from core.tenant import own_company

    from .contract_templates import contract_rules

    rules = contract_rules(own_company())
    blocks = expired and gates_new_deals(pick, rules["gating_kinds"]) and rules["expired_action"] == "block"
    return {
        "contract_id": pick.pk,
        "deal_id": pick.deal_id,
        "number": pick.number,
        "state": state_of(pick, today),
        "valid_until": pick.valid_until,
        "last_notice_date": pick.last_notice_date,
        "foreign": pick.term_foreign,
        "blocks_new_work": bool(blocks),
    }
