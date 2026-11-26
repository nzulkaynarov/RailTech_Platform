"""ДОК-10: договор — только из утверждённых шаблонов (решение владельца 2026-11-23, DECISIONS).

Шаблон договора — запись `DocumentTemplate` вида `CONTRACT` с утверждением: черновик → на утверждении → утверждён,
редакция, кто и когда утвердил, для кого (клиент / партнёр) и предмет (поставка / услуги). Тело — блоки с замком
(`{{doc.*}}`, `document_blocks`) и переменные из сделки; в сделке текст не правится: договор хранит замороженную
редакцию (`Contract.frozen_template_body`), шаблон, номер редакции и не меняется, когда выходит новая.

Что здесь решается фактами, а не кодом:

* утверждает держатель права `contract.approve_template` (раздел каталога `eds.visa.legal`, зона «Право»);
* в сделке предлагаются только `approved` и активные шаблоны вида контрагента (`offered_templates`);
* правила — настройки компании (`CompanySettings.contract_*`): авто-отправка, наша подпись до отправки, допустимость
  отступлений, шаблон по умолчанию на вид контрагента;
* что мешает отправить договор клиенту — ОДНА проверка `contract_flow.send_blocker` (шаблон ДОК-10 + визы Х-1, #833):
  здесь только факты для неё — `deviation_state`, `visas_required` (визы нужны с отступлением; по утверждённому шаблону
  без отступления их нет), `requires_our_signature`.

Переходный режим: пока у компании нет ни одного утверждённого шаблона вида контрагента, договор собирается как раньше
(`Contract.template` пуст) — без блокировок и настроек; владелец утверждает редакцию 1 в «Документы · Шаблоны · Договоры».
"""

from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone
from documents.models.documents import ContractSubject, CounterpartyKind, DocumentTemplate, TemplateApproval

from accounts.models import CustomUser
from core.contract_term import ContractExpiredAction, ContractTermRule

from ..models import ActivityLog

CONTRACT_KIND = "CONTRACT"
APPROVE_PERMISSION = "contract.approve_template"
MAX_DEVIATION_CHARS = 4000

# Запасной выбор без настройки: поставка раньше услуг (не по алфавиту кода)
_SUBJECT_ORDER = {ContractSubject.SUPPLY: 0, ContractSubject.SERVICES: 1}

_PARTNER_TYPES = {"SUPPLIER", "MANUFACTURER", "LOGISTICS_PROVIDER"}


# ── Права ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def is_approver(user) -> bool:
    """Держатель права `contract.approve_template` в своей компании (администратор — всегда). Системный вызов (`None`) — нет."""
    if user is None:
        return False
    from accounts.services.permissions import member_has_permission
    from core.tenant import own_company_id

    return member_has_permission(user, own_company_id(), APPROVE_PERMISSION)


def _may_manage(user) -> bool:
    from .contract_flow import is_staff, may

    return bool(is_staff(user) and may(user, "contract.manage"))


# ── Настройки ──────────────────────────────────────────────────────────────────────────────────────────────────────


def contract_rules(company) -> dict:
    """Правила договора по шаблону — настройки компании («Правила работы · Продажи»); нет строки — умолчания."""
    from parties.models.company_settings import CompanySettings

    row = CompanySettings.objects.filter(company=company).first() if company is not None else None
    return {
        "auto_send": True if row is None else row.contract_auto_send,
        "sign_before_send": True if row is None else row.contract_sign_before_send,
        "deviations_allowed": True if row is None else row.contract_deviations_allowed,
        "default_client": None if row is None else row.default_client_contract_template_id,
        "default_partner": None if row is None else row.default_partner_contract_template_id,
        # ДС-1: срок договора — правила компании; шаблон переопределяет часть (`contract_term.term_rules`)
        "term_rule": ContractTermRule.CALENDAR_YEAR if row is None else row.contract_term_rule,
        "auto_renew": True if row is None else row.contract_auto_renew,
        "notice_days": 30 if row is None else row.contract_notice_days,
        "next_year_from_day": 1 if row is None else row.contract_next_year_from_day,
        "remind_first_days": 30 if row is None else row.contract_remind_first_days,
        "remind_last_days": 7 if row is None else row.contract_remind_last_days,
        "foreign_remind_days": 45 if row is None else row.contract_foreign_remind_days,
        "expired_action": ContractExpiredAction.BLOCK if row is None else row.contract_expired_action,
        "foreign_by_agreement": True if row is None else row.contract_foreign_by_agreement,
        "gating_kinds": [] if row is None else list(row.contract_gating_kinds or []),
    }


def counterparty_kind_of(company) -> str:
    """Вид контрагента сделки: партнёр — компания только поставщик/производитель/логист; иначе клиент."""
    if company is None:
        return CounterpartyKind.CLIENT
    codes = set(company.types.values_list("code", flat=True)) if hasattr(company, "types") else set()
    if codes and not ({"CLIENT"} & codes) and codes & _PARTNER_TYPES:
        return CounterpartyKind.PARTNER
    return CounterpartyKind.CLIENT


# ── Шаблоны: редакции и утверждение ────────────────────────────────────────────────────────────────────────────────


def contract_templates_of(company):
    return DocumentTemplate.objects.filter(company=company, kind__code=CONTRACT_KIND).select_related(
        "kind", "approved_by"
    )


def offered_templates(company, counterparty_kind: str):
    """Что предлагается в сделке: утверждённые, действующие шаблоны вида контрагента своей компании."""
    return contract_templates_of(company).filter(
        approval_status=TemplateApproval.APPROVED, is_active=True, counterparty_kind=counterparty_kind
    )


# ── Базовые документы компании (ОСН-1) ─────────────────────────────────────────────────────────────────────────────────

BASE_ROLES = ("partnership", "nda", "offer")


def partner_base_roles(company) -> list[str]:
    """Роли базовых документов, которые компания выдаёт кандидатам в партнёры, — настройка компании, не код."""
    from parties.models.company_settings import CompanySettings, default_partner_base_roles

    row = CompanySettings.objects.filter(company=company).first() if company is not None else None
    roles = default_partner_base_roles() if row is None else list(row.partner_base_roles or [])
    return [role for role in BASE_ROLES if role in roles]


def base_template(company, role: str):
    """Утверждённая действующая редакция базового документа роли: она одна на компанию (`doctpl_one_active_base_role`)."""
    return (
        contract_templates_of(company)
        .filter(base_role=role, approval_status=TemplateApproval.APPROVED, is_active=True)
        .order_by("-edition")
        .first()
    )


def edition_chain_ids(template) -> list[int]:
    """Предыдущие редакции шаблона по цепочке `previous_edition` (без него самого)."""
    seen: list[int] = []
    node = template.previous_edition
    while node is not None and node.pk not in seen:
        seen.append(node.pk)
        node = node.previous_edition
    return seen


def is_locked(template) -> bool:
    """Закреплённый текст шаблона договора правится только в черновике."""
    return template.kind.code == CONTRACT_KIND and template.approval_status != TemplateApproval.DRAFT


def _journal(template, user, event_code: str, action: str, **params) -> None:
    ActivityLog.objects.create(
        action=action,
        detail=f"{template.name}, ред. {template.edition}",
        event_code=event_code,
        event_params={"template_id": template.id, "name": template.name, "edition": template.edition, **params},
        user=user,
        level="INFO",
        entity_type="document_template",
        entity_id=template.id,
        company_id=template.company_id,
    )


def create_from_standard(company, user, *, name: str, counterparty_kind: str, subject: str, base_role: str = ""):
    """Новый шаблон договора (черновик, редакция 1) из стандартного текста: образец платформы либо зашитый текст."""
    from core.seeds.documents import CONTRACT_BODY

    from .generated_documents import create_template

    name = (name or "").strip()
    if not name:
        return None, "TEMPLATE_NAME_REQUIRED"
    if counterparty_kind not in CounterpartyKind.values:
        return None, "TEMPLATE_COUNTERPARTY_INVALID"
    if subject not in ContractSubject.values:
        return None, "TEMPLATE_SUBJECT_INVALID"
    if base_role and base_role not in BASE_ROLES:
        return None, "TEMPLATE_BASE_ROLE_INVALID"
    sample = DocumentTemplate.objects.filter(company__isnull=True, is_sample=True, kind__code=CONTRACT_KIND).first()
    # Черновик: целостность блоков проверяется при отправке на утверждение, не при создании.
    template = create_template(
        company,
        user,
        name=name,
        kind_code=CONTRACT_KIND,
        body_html=sample.body_html if sample else CONTRACT_BODY,
        is_active=False,
    )
    template.counterparty_kind = counterparty_kind
    template.subject = subject
    template.base_role = base_role or ""
    template.approval_status = TemplateApproval.DRAFT
    template.save(update_fields=["counterparty_kind", "subject", "base_role", "approval_status"])
    _journal(template, user, "contract_template.created", "Создан шаблон договора")
    return template, None


@transaction.atomic
def new_edition(template, user) -> Tuple[Optional[DocumentTemplate], Optional[str]]:
    """«Новая редакция»: копия утверждённого шаблона в черновике с номером на единицу больше; прежняя остаётся своей."""
    if template.kind.code != CONTRACT_KIND:
        return None, "TEMPLATE_NOT_CONTRACT"
    if template.approval_status != TemplateApproval.APPROVED:
        return None, "TEMPLATE_EDITION_NEEDS_APPROVED"
    if template.next_editions.filter(
        approval_status__in=[TemplateApproval.DRAFT, TemplateApproval.ON_APPROVAL]
    ).exists():
        return None, "TEMPLATE_EDITION_IN_PROGRESS"
    copy = DocumentTemplate.objects.create(
        company=template.company,
        name=template.name,
        kind=template.kind,
        body_html=template.body_html,
        body_html_uz=template.body_html_uz,
        body_html_en=template.body_html_en,
        placeholders_used=list(template.placeholders_used or []),
        is_active=False,  # предлагается только после утверждения
        created_by=user,
        approval_status=TemplateApproval.DRAFT,
        edition=template.edition + 1,
        previous_edition=template,
        counterparty_kind=template.counterparty_kind,
        subject=template.subject,
        base_role=template.base_role,
        term_rule=template.term_rule,
        renewal_mode=template.renewal_mode,
        notice_days=template.notice_days,
        confidentiality_years=template.confidentiality_years,
        trade_secret_indefinite=template.trade_secret_indefinite,
        renewal_notice=dict(template.renewal_notice or {}),
    )
    _journal(copy, user, "contract_template.new_edition", "Новая редакция шаблона договора")
    return copy, None


def unknown_placeholders(template) -> list[str]:
    """Подстановки текста шаблона (все языки), которых система не знает: в договор они попали бы как есть."""
    from .document_blocks import preview_block_stubs
    from .document_placeholders import RESOLVERS, extract_placeholders

    known = set(RESOLVERS) | set(preview_block_stubs())
    seen: list[str] = []
    for body in (template.body_html, template.body_html_uz, template.body_html_en):
        for code in extract_placeholders(body or ""):
            if code not in known and code not in seen:
                seen.append(code)
    return seen


@transaction.atomic
def submit_for_approval(template, user) -> Tuple[Optional[DocumentTemplate], Optional[str]]:
    from .document_blocks import missing_required_blocks

    if template.kind.code != CONTRACT_KIND:
        return None, "TEMPLATE_NOT_CONTRACT"
    if not _may_manage(user):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if template.approval_status != TemplateApproval.DRAFT:
        return None, "TEMPLATE_TRANSITION_NOT_ALLOWED"
    if not template.counterparty_kind or not template.subject:
        return None, "TEMPLATE_COUNTERPARTY_REQUIRED"
    if missing_required_blocks(CONTRACT_KIND, template.body_html):
        return None, "TEMPLATE_MISSING_REQUIRED_BLOCKS"
    # Неизвестная подстановка остаётся в договоре как есть: на утверждение такой текст не уходит
    if unknown_placeholders(template):
        return None, "TEMPLATE_UNKNOWN_PLACEHOLDERS"
    template.approval_status = TemplateApproval.ON_APPROVAL
    template.submitted_at = timezone.now()
    template.save(update_fields=["approval_status", "submitted_at", "updated_at"])
    _journal(template, user, "contract_template.submitted", "Шаблон договора отправлен на утверждение")
    return template, None


@transaction.atomic
def approve(template, user) -> Tuple[Optional[DocumentTemplate], Optional[str]]:
    """Утвердить: только держатель `contract.approve_template`; предыдущая утверждённая редакция снимается с показа."""
    if template.kind.code != CONTRACT_KIND:
        return None, "TEMPLATE_NOT_CONTRACT"
    if not is_approver(user):
        return None, "TEMPLATE_APPROVAL_FORBIDDEN"
    template = DocumentTemplate.objects.select_for_update().select_related("kind").get(pk=template.pk)
    if template.approval_status != TemplateApproval.ON_APPROVAL:
        return None, "TEMPLATE_TRANSITION_NOT_ALLOWED"
    now = timezone.now()
    if template.base_role:
        # ОСН-1: одна действующая редакция базового документа на роль. Прежние редакции этого же шаблона снимаются с показа;
        # другой действующий шаблон той же роли — отказ: новая редакция — исключение, а не второй документ.
        active = DocumentTemplate.objects.filter(
            company=template.company,
            base_role=template.base_role,
            approval_status=TemplateApproval.APPROVED,
            is_active=True,
        ).exclude(pk=template.pk)
        if active.exclude(pk__in=edition_chain_ids(template)).exists():
            return None, "TEMPLATE_BASE_ROLE_TAKEN"
        active.update(is_active=False)
    # Одна действующая редакция на (вид контрагента, предмет, название): прежние остаются утверждёнными, но не предлагаются.
    DocumentTemplate.objects.filter(
        company=template.company,
        kind=template.kind,
        name=template.name,
        counterparty_kind=template.counterparty_kind,
        subject=template.subject,
        approval_status=TemplateApproval.APPROVED,
        is_active=True,
    ).exclude(pk=template.pk).update(is_active=False)
    template.approval_status = TemplateApproval.APPROVED
    template.approved_by = user
    template.approved_at = now
    template.is_active = True
    template.save(update_fields=["approval_status", "approved_by", "approved_at", "is_active", "updated_at"])
    _carry_defaults_to_edition(template)
    _journal(template, user, "contract_template.approved", "Шаблон договора утверждён")
    return template, None


def _carry_defaults_to_edition(template) -> None:
    """Настройка хранит id редакции; новая утверждённая редакция наследует роль «по умолчанию» у прежних по цепочке."""
    from parties.models.company_settings import CompanySettings

    ancestors, node = [], template.previous_edition
    while node is not None and node.pk not in ancestors:
        ancestors.append(node.pk)
        node = node.previous_edition
    if not ancestors:
        return
    for field in ("default_client_contract_template", "default_partner_contract_template"):
        CompanySettings.objects.filter(company=template.company, **{f"{field}_id__in": ancestors}).update(
            **{f"{field}_id": template.pk}
        )


@transaction.atomic
def return_to_draft(template, user) -> Tuple[Optional[DocumentTemplate], Optional[str]]:
    """Вернуть на доработку: держатель права снимает шаблон с утверждения (редактируется как черновик)."""
    if not is_approver(user):
        return None, "TEMPLATE_APPROVAL_FORBIDDEN"
    if template.approval_status != TemplateApproval.ON_APPROVAL:
        return None, "TEMPLATE_TRANSITION_NOT_ALLOWED"
    template.approval_status = TemplateApproval.DRAFT
    template.submitted_at = None
    template.save(update_fields=["approval_status", "submitted_at", "updated_at"])
    _journal(template, user, "contract_template.returned", "Шаблон договора возвращён в черновик")
    return template, None


# ── Выбор шаблона для договора ─────────────────────────────────────────────────────────────────────────────────────


def pick_template(seller_company, counterparty_company, template_id=None):
    """Какой шаблон берёт договор: `(шаблон | None, ошибка)`.

    Выбранный менеджером должен быть в предложенных (`CONTRACT_TEMPLATE_NOT_OFFERED`). Без выбора — шаблон по умолчанию
    из настроек, иначе первый предложенный (поставка раньше услуг). Предложенных нет — `None`: прежний путь (переходный
    режим, см. docstring модуля).
    """
    kind = counterparty_kind_of(counterparty_company)
    offered = sorted(offered_templates(seller_company, kind), key=lambda t: (_SUBJECT_ORDER.get(t.subject, 99), t.name))
    if template_id:
        chosen = next((t for t in offered if t.id == template_id), None)
        return (chosen, None) if chosen else (None, "CONTRACT_TEMPLATE_NOT_OFFERED")
    if not offered:
        return None, None
    rules = contract_rules(seller_company)
    default_id = rules["default_partner"] if kind == CounterpartyKind.PARTNER else rules["default_client"]
    chosen = next((t for t in offered if t.id == default_id), None)
    return (chosen or offered[0]), None


def unfilled_variables(contract, body_html: str) -> list:
    """Незаполненные места договора: токены без значения и пустые обязательные данные сделки. Пусто — можно регистрировать."""
    from core.currency import BASE_CURRENCY

    from .document_blocks import render_contract_body
    from .document_placeholders import PLACEHOLDER_RE
    from .documents import document_brand_context, document_totals

    problems = []
    if not contract.total_amount or float(contract.total_amount) <= 0:
        problems.append("doc.total")
    company = contract.deal.company
    if company is None or not (company.name or "").strip():
        problems.append("buyer.name")
    ccy = contract.currency.code if contract.currency else BASE_CURRENCY
    brand = document_brand_context(_own_seller(contract))
    totals = document_totals(
        ccy=ccy, vat_rate=contract.quote.vat_rate if contract.quote_id else None, total=contract.total_amount
    )
    from .documents.projection import client_billable_lines

    items = client_billable_lines(contract.quote)
    rendered = render_contract_body(
        contract,
        items,
        totals,
        ccy,
        None,
        seller=brand.get("seller"),
        seller_profile=brand.get("seller_profile"),
        body_html=body_html,
    )
    for match in PLACEHOLDER_RE.finditer(rendered):
        code = match.group(1).strip()
        if code not in problems:
            problems.append(code)
    return problems


# ── Отправка: что мешает ───────────────────────────────────────────────────────────────────────────────────────────


def deviation_state(contract) -> str:
    """none | requested | approved | rejected — из фактов договора."""
    if not contract.deviation_requested_at:
        return "none"
    return contract.deviation_decision or "requested"


def visas_required(contract) -> bool:
    """Договор идёт по маршруту виз (Х-1) только с отступлением от шаблона; по утверждённому шаблону виз нет."""
    return contract.template_id is not None and deviation_state(contract) in {"requested", "approved"}


def requires_our_signature(contract) -> bool:
    """Правило компании «наша подпись до отправки» не выполнено: договор по шаблону без подписи продавца."""
    return contract_rules(_own_seller(contract))["sign_before_send"] and contract.manager_signed_at is None


def seller_of_quote(quote):
    """Продавец КП; КП без исполнителя — своя компания (шаблоны принадлежат компании, не «никому»)."""
    from accounts.models import Company
    from core.tenant import own_company_id

    from .quotes import _quote_seller_company

    return _quote_seller_company(quote) or Company.objects.filter(pk=own_company_id()).first()


def _own_seller(contract):
    return seller_of_quote(contract.quote)


def path_steps(contract) -> list:
    """Путь договора для карточки проекта — по фактам: каждый шаг `done` / `current` / `next` с датой факта."""
    from ..constants import ContractStatusCode as S

    code = contract.status.code if contract.status_id else ""
    sent = code not in {"", S.DRAFT}
    signed = code == S.SIGNED
    ours = contract.manager_signed_at is not None
    rules = contract_rules(_own_seller(contract))
    steps = [("assembled", True, contract.created_at)]
    if rules["sign_before_send"]:
        steps.append(("our_signature", ours, contract.manager_signed_at))
    steps.append(("in_cabinet", sent, contract.updated_at if sent else None))
    steps.append(("signed_both", signed, contract.signed_at or (contract.client_signed_at if signed else None)))
    result, found_current = [], False
    for key, done, at in steps:
        if done:
            state = "done"
        elif not found_current:
            state, found_current = "current", True
        else:
            state = "next"
        result.append({"key": key, "state": state, "at": at})
    return result


# ── Отступление от шаблона ─────────────────────────────────────────────────────────────────────────────────────────


def _holders_to_notify(company_id):
    from accounts.models import CustomUser as User
    from accounts.services.permissions import member_has_permission

    users = User.objects.filter(
        is_active=True, memberships__company_id=company_id, memberships__is_active=True
    ).distinct()
    return [u for u in users if member_has_permission(u, company_id, APPROVE_PERMISSION)]


@transaction.atomic
def request_deviation(contract_id: int, user: CustomUser, text: str):
    """«Запросить отступление»: заявка держателю «Право»; до решения договор клиенту не уходит. `(договор, None)` или `(None, код)`."""
    from ..models import Contract

    contract = (
        Contract.objects.select_for_update(of=("self",))
        .select_related("deal__company", "quote", "status")
        .get(pk=contract_id)
    )
    if not _may_manage(user):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if contract.template_id is None:
        return None, "CONTRACT_NOT_FROM_TEMPLATE"
    if not contract_rules(_own_seller(contract))["deviations_allowed"]:
        return None, "CONTRACT_DEVIATIONS_DISABLED"
    if contract.status_code != "DRAFT":
        return None, "CONTRACT_ALREADY_SENT"
    text = (text or "").strip()
    if not text:
        return None, "DEVIATION_TEXT_REQUIRED"
    if len(text) > MAX_DEVIATION_CHARS:
        return None, "DEVIATION_TEXT_TOO_LONG"
    if deviation_state(contract) == "requested":
        return None, "DEVIATION_ALREADY_REQUESTED"
    contract.deviation_text = text
    contract.deviation_requested_by = user
    contract.deviation_requested_at = timezone.now()
    contract.deviation_decision = ""
    contract.deviation_decided_by = None
    contract.deviation_decided_at = None
    contract.save(
        update_fields=[
            "deviation_text",
            "deviation_requested_by",
            "deviation_requested_at",
            "deviation_decision",
            "deviation_decided_by",
            "deviation_decided_at",
            "updated_at",
        ]
    )
    ActivityLog.objects.create(
        action="Запрошено отступление от шаблона договора",
        detail=f"Договор {contract.number} / сделка #{contract.deal_id}",
        event_code="contract.deviation_requested",
        event_params={"number": contract.number, "deal_id": contract.deal_id, "text": text},
        user=user,
        level="INFO",
        entity_type="contract",
        entity_id=contract.id,
        deal=contract.deal,
        company_id=contract.deal.company_id,
    )
    _notify_holders(contract)
    return contract, None


def _notify_holders(contract) -> None:
    from urllib.parse import quote

    from core.tenant import own_company_id
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    info = NotificationType.objects.filter(code="INFO").first()
    # Карточка проекта (путь по бизнес-номеру сделки, как в Платформе), а не общий список
    link = f"/eds/projects/{quote(contract.deal.number or f'D-{contract.deal_id}', safe='')}"
    for holder in _holders_to_notify(own_company_id()):
        notif = Notification.objects.create(
            user=holder,
            type=info,
            title="Запрос на отступление от шаблона договора",
            message=f"Договор {contract.number}: {contract.deviation_text[:200]}",
            link=link,
            deal=contract.deal,
            event_code="contract.deviation_requested",
            event_params={"number": contract.number},
        )
        push_notification_ws(notif)


@transaction.atomic
def decide_deviation(contract_id: int, user: CustomUser, *, approve_it: bool):
    """Решение держателя «Право»: одобрено (текст отступления входит в договор, дальше — визы) или отклонено."""
    from ..models import Contract
    from ..tasks import render_document_pdf

    if not is_approver(user):
        return None, "DEVIATION_DECISION_FORBIDDEN"
    contract = (
        Contract.objects.select_for_update(of=("self",))
        .select_related("deal__company", "quote", "status")
        .get(pk=contract_id)
    )
    if deviation_state(contract) != "requested":
        return None, "DEVIATION_NOT_REQUESTED"
    contract.deviation_decision = "approved" if approve_it else "rejected"
    contract.deviation_decided_by = user
    contract.deviation_decided_at = timezone.now()
    fields = ["deviation_decision", "deviation_decided_by", "deviation_decided_at", "updated_at"]
    if approve_it:
        contract.notes = (contract.notes + "\n" if contract.notes else "") + contract.deviation_text
        fields.append("notes")
    contract.save(update_fields=fields)
    ActivityLog.objects.create(
        action="Отступление от шаблона одобрено" if approve_it else "Отступление от шаблона отклонено",
        detail=f"Договор {contract.number} / сделка #{contract.deal_id}",
        event_code="contract.deviation_approved" if approve_it else "contract.deviation_rejected",
        event_params={"number": contract.number, "deal_id": contract.deal_id},
        user=user,
        level="INFO",
        entity_type="contract",
        entity_id=contract.id,
        deal=contract.deal,
        company_id=contract.deal.company_id,
    )
    if approve_it:
        transaction.on_commit(lambda: render_document_pdf.delay("contract", contract.id))
    else:
        try_auto_send(contract)  # без отступления договор снова идёт обычным путём
    return contract, None


# ── Наша подпись и авто-отправка ───────────────────────────────────────────────────────────────────────────────────


@transaction.atomic
def sign_by_company(contract_id: int, user: CustomUser):
    """Подпись от компании до отправки (настройка «Продажи»): право `contract.sign`, договор по шаблону, ещё не ушёл клиенту."""
    from ..models import Contract
    from ..tasks import render_document_pdf
    from .contract_flow import is_staff, may

    contract = (
        Contract.objects.select_for_update(of=("self",))
        .select_related("deal__company", "quote", "status")
        .get(pk=contract_id)
    )
    if not (is_staff(user) and may(user, "contract.sign")):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if contract.template_id is None:
        return None, "CONTRACT_NOT_FROM_TEMPLATE"
    if contract.status_code != "DRAFT":
        return None, "CONTRACT_ALREADY_SENT"
    if contract.manager_signed_at is not None:
        return None, "CONTRACT_ALREADY_SIGNED_BY_US"
    contract.manager_signer = user
    contract.manager_signed_at = timezone.now()
    contract.save(update_fields=["manager_signer", "manager_signed_at", "updated_at"])
    ActivityLog.objects.create(
        action="Договор подписан от компании до отправки",
        detail=f"Договор {contract.number} / сделка #{contract.deal_id}",
        event_code="contract.signed_by_us",
        event_params={"number": contract.number, "deal_id": contract.deal_id},
        user=user,
        level="INFO",
        entity_type="contract",
        entity_id=contract.id,
        deal=contract.deal,
        company_id=contract.deal.company_id,
    )
    transaction.on_commit(lambda: render_document_pdf.delay("contract", contract.id))
    try_auto_send(contract)
    return contract, None


def try_auto_send(contract) -> bool:
    """Авто-отправка в Кабинет: по настройке, договор по шаблону, без отступления на решении и без других помех.

    С отступлением (одобренным или нет решения) договор сам не уходит: его отправляют после виз.
    """
    from .contract_flow import apply_transition, send_blocker

    if contract.template_id is None or contract.status_code != "DRAFT":
        return False
    if not contract_rules(_own_seller(contract))["auto_send"]:
        return False
    if visas_required(contract) or send_blocker(contract):
        return False
    sent, error = apply_transition(contract.id, "send_to_client", None)
    return error is None and sent is not None
