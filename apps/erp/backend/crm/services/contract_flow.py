"""Статусы договора по SPEC-v3 §2.4 (D2-5): договор подписывают ВНЕ платформы, ERP фиксирует статусы и скан.

Подпись кликом (`[MANUAL_MODE]`) в Платформе не предлагается: договор уходит клиенту на согласование редакции, затем его
выставляют у оператора ЭДО, а после подписи обеими сторонами бухгалтер прикрепляет скан — и договор «Подписан».

Слова SPEC и коды ERP (строки словаря `ContractStatus` не переименовываются — на них стоят портал и шов):

| Слово SPEC (`contract_v3_status`) | Код ERP                    | Кто меняет                          |
|-----------------------------------|----------------------------|-------------------------------------|
| `project`                         | `DRAFT`, `PENDING_CLIENT`  | система (из КП), бухгалтер          |
| `client_agreed`                   | `PENDING_MANAGER`          | клиент (кабинет) или бухгалтер      |
| `issued_at_operator`              | `ISSUED_EXTERNAL`          | бухгалтер, директор (`contract.sign`) |
| `signed`                          | `SIGNED`                   | бухгалтер, директор (скан)          |
| `rejected`                        | `REJECTED`                 | бухгалтер (со слов клиента)         |
| `cancelled`                       | `CANCELLED`                | администратор                       |

`DRAFT` — проект не отправлен клиенту; `PENDING_CLIENT` — ушёл на согласование (так рождается договор после акцепта КП).
Допустимые переходы — таблица `TRANSITIONS`; любой другой — `CONTRACT_TRANSITION_NOT_ALLOWED` (HTTP 409). Права: подготовка
(`contract.manage`) — отправить, отметить согласие клиента, отклонить, вернуть в проект; подпись от компании
(`contract.sign`) — «выставлен у оператора» и скан. Проверка и во вьюхе (`required_permissions`), и здесь.

Каждый переход — в одной транзакции: строка договора под `select_for_update`, запись журнала (`ActivityLog`: кто, когда,
что, причина), событие шины `contract.status_changed`. Подписанный скан — PDF или изображение (сигнатура байтов,
`core.validators.validate_scan_upload`); «Подписан» закрывает договор для всех правок и, как раньше при подписи обеими
сторонами, ведёт сделку в `CLOSED_WON` (счёт на предоплату создаётся задачей `auto_invoice_on_closed_won`).
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import CustomUser
from core.validators import validate_scan_upload

from ..constants import ContractStatusCode as S
from ..models import ActivityLog, Contract

#: Слово SPEC → коды ERP (обратное сопоставление — `contract_v3_status`).
V3_STATUS = {
    S.DRAFT: "project",
    S.PENDING_CLIENT: "project",
    S.PENDING_MANAGER: "client_agreed",
    S.ISSUED_EXTERNAL: "issued_at_operator",
    S.SIGNED: "signed",
    S.REJECTED: "rejected",
    S.CANCELLED: "cancelled",
}


@dataclass(frozen=True)
class Transition:
    """Один допустимый переход: из каких статусов ERP, в какой, под каким правом, нужна ли причина или файл."""

    action: str
    sources: frozenset
    target: str
    permission: str
    event_code: str
    title: str
    needs_reason: bool = False
    needs_file: bool = False
    #: Действие клиента записывает сотрудник (A2 волны 18a): канал и лицо со стороны клиента обязательны.
    needs_on_behalf: bool = False


TRANSITIONS = {
    t.action: t
    for t in (
        Transition(
            "send_to_client",
            frozenset({S.DRAFT}),
            S.PENDING_CLIENT,
            "contract.manage",
            "contract.sent_to_client",
            "Проект договора отправлен клиенту на согласование",
        ),
        Transition(
            "client_agreed",
            frozenset({S.PENDING_CLIENT}),
            S.PENDING_MANAGER,
            "contract.manage",
            "contract.client_agreed",
            "Редакция договора согласована клиентом",
            needs_on_behalf=True,
        ),
        Transition(
            "reject",
            frozenset({S.PENDING_CLIENT, S.PENDING_MANAGER, S.ISSUED_EXTERNAL}),
            S.REJECTED,
            "contract.manage",
            "contract.rejected",
            "Договор отклонён клиентом",
            needs_reason=True,
        ),
        Transition(
            "revise",
            frozenset({S.REJECTED}),
            S.DRAFT,
            "contract.manage",
            "contract.revised",
            "Проект договора возвращён в работу",
        ),
        Transition(
            "mark_issued",
            frozenset({S.PENDING_MANAGER}),
            S.ISSUED_EXTERNAL,
            "contract.sign",
            "contract.issued_external",
            "Договор выставлен у оператора",
        ),
        Transition(
            "attach_scan",
            frozenset({S.PENDING_MANAGER, S.ISSUED_EXTERNAL}),
            S.SIGNED,
            "contract.sign",
            "contract.scan_attached",
            "Договор отмечен подписанным",
            needs_file=True,
        ),
    )
}


def _status_code(contract) -> Optional[str]:
    return contract.status.code if contract.status_id else None


def contract_v3_status(contract) -> str:
    """Слово статуса по SPEC-v3 §2.4; неизвестный или пустой код ERP — `project`."""
    return V3_STATUS.get(_status_code(contract) or "", "project")


def contract_sent_to_client(contract) -> bool:
    """Проект ушёл клиенту (всё, кроме `DRAFT`): клиенту он виден в портале."""
    return _status_code(contract) != S.DRAFT


def allowed_actions(contract, user) -> list:
    """Действия, доступные сейчас ЭТОМУ пользователю: допустимы из текущего статуса и разрешены его правами.

    Единый источник для карточки проекта: страница не вычисляет сама, что можно (CONVENTIONS Платформы, правило 2).
    """
    code = _status_code(contract)
    actions = [
        t.action for t in TRANSITIONS.values() if code in t.sources and may(user, t.permission) and is_staff(user)
    ]
    # Х-1 и ДОК-10: «Отправить клиенту» не предлагается, пока отправка ответит 409 (причина — `send_blocker`).
    if "send_to_client" in actions and send_blocker(contract) is not None:
        actions.remove("send_to_client")
    return actions


#: Причины блокировки отправки по правилам шаблона (ДОК-10); визы — коды `contract_visas` (Х-1).
TEMPLATE_BLOCKER_WORDS = {
    "CONTRACT_DEVIATION_PENDING": "Отступление от шаблона ждёт решения: отправить договор клиенту можно после него.",
    "CONTRACT_NEEDS_OUR_SIGNATURE": "Нужна наша подпись: по правилам компании договор уходит клиенту подписанным.",
}


def send_blocker(contract) -> Optional[dict]:
    """ЕДИНАЯ проверка «можно ли отправить договор клиенту» (`None` — можно) для всех путей: действие `send_to_client`,
    список действий, карточка проекта, «Мои задачи» и Платформа. Результат — `{code, message, missing, ...}`.

    Порядок и правила (ДОК-10 + Х-1, ADR-0025):

    1. договор по утверждённому шаблону без отступления визам не подчиняется (а): ему мешает только наша подпись,
       если компания её требует до отправки (`CONTRACT_NEEDS_OUR_SIGNATURE`);
    2. отступление ждёт решения — своя причина (в): `CONTRACT_DEVIATION_PENDING`;
    3. договор с одобренным отступлением и договор не из утверждённого шаблона (переходный режим, прежние) идут по
       маршруту виз (б): коды `visas_*` из `contract_visas.send_blocker`, недостающие визы названы словами;
    4. после виз — наша подпись, если компания требует её до отправки.
    """
    from . import contract_templates as templates
    from .contract_visas import _blocker
    from .contract_visas import send_blocker as visas_blocker

    def template_blocker(code: str) -> dict:
        return _blocker(code, TEMPLATE_BLOCKER_WORDS[code])

    if contract.template_id is None:
        return visas_blocker(contract)  # переходный режим и прежние договоры: маршрут виз Х-1
    if templates.deviation_state(contract) == "requested":
        return template_blocker("CONTRACT_DEVIATION_PENDING")
    if templates.visas_required(contract):
        blocker = visas_blocker(contract)
        if blocker is not None:
            return blocker
    if templates.requires_our_signature(contract):
        return template_blocker("CONTRACT_NEEDS_OUR_SIGNATURE")
    return None


def _drop_company_stamp(contract) -> list:
    """Х-1: «Доработать» — новая редакция, штамп подписи компании на ней не остаётся.

    Иначе договор, подписанный директором до отправки и отклонённый клиентом, не проходит маршрут заново: «На подпись»
    отвечает `ALREADY_SIGNED`, а визы прежней подписи пропускали бы новую редакцию. Запрос подписи закрывается как
    устаревший, проверка по коду показывает «Отозван»; маршрут «визы → клиенту → подпись» идёт с начала.
    """
    from integration.models import CommercialSigningRequest as Request
    from portal.models import PortalDocumentVerification

    code = contract.verification_code
    if not code:
        return []
    PortalDocumentVerification.objects.filter(code=code).update(
        status="revoked", revoked_at=timezone.now(), revocation_reason="Новая редакция договора"
    )
    Request.objects.filter(kind="contract", object_id=contract.pk, status=Request.Status.SIGNED).update(
        status=Request.Status.STALE, comment="Новая редакция договора: подпись прежней не переносится."
    )
    contract.verification_code = ""
    contract.signatory_name = ""
    contract.signatory_position = ""
    contract.signatory_basis_text = ""
    contract.signed_at = None
    return ["verification_code", "signatory_name", "signatory_position", "signatory_basis_text", "signed_at"]


def is_staff(user) -> bool:
    from accounts.services.permissions import is_seller

    return bool(user is None or getattr(user, "is_superuser", False) or is_seller(user))


def may(user, permission: str) -> bool:
    """Право действовать от имени своей компании (администратор — всегда; `None` — внутренний вызов системы)."""
    if user is None:
        return True
    from accounts.services.permissions import member_has_permission
    from core.tenant import own_company_id

    return member_has_permission(user, own_company_id(), permission)


def _publish(contract, actor, *, reason: str = "") -> None:
    """Событие `contract.status_changed` в транзакции перехода (откат изменения — нет события)."""
    from integration.services import events

    events.publish_contract_status_changed(
        contract,
        contract_v3_status(contract),
        sent_to_client=contract_sent_to_client(contract),
        reason=reason or None,
        actor=events.build_actor(actor) if actor is not None else None,
    )


def publish_current_status(contract, actor=None, *, reason: str = "") -> None:
    """Публикует текущий статус договора: после создания и после переходов старых путей (подпись клиента в портале)."""
    _publish(contract, actor, reason=reason)


#: Как клиент сообщил о действии (тот же список, что у КП, `crm/services/quotes/on_behalf.py`).
ON_BEHALF_CHANNELS = ("phone", "email", "messenger", "in_person", "paper")


def _on_behalf_note(transition: Transition, channel: str, person: str) -> Tuple[Optional[dict], Optional[str]]:
    if not transition.needs_on_behalf:
        return None, None
    if channel not in ON_BEHALF_CHANNELS:
        return None, "CHANNEL_INVALID"
    person = (person or "").strip()
    if not person or len(person) > 200:
        return None, "COUNTERPARTY_PERSON_REQUIRED"
    return {"channel": channel, "counterparty_person": person}, None


def _journal(
    contract, transition: Transition, actor, *, reason: str, note: str, before: str, on_behalf: Optional[dict] = None
) -> None:
    ActivityLog.objects.create(
        action=transition.title,
        detail=f"Договор {contract.number} / сделка #{contract.deal_id}",
        event_code=transition.event_code,
        event_params={
            "number": contract.number,
            "deal_id": contract.deal_id,
            "from": before,
            "to": _status_code(contract),
            **({"note": note} if note else {}),
            **({"on_behalf": on_behalf} if on_behalf else {}),
        },
        user=actor,
        level="WARNING" if transition.action == "reject" else "INFO",
        entity_type="contract",
        entity_id=contract.id,
        reason=reason,
        deal=contract.deal,
        company_id=contract.deal.company_id,
    )


def _check_scan(file_obj) -> Optional[str]:
    if file_obj is None:
        return "SCAN_REQUIRED"
    try:
        validate_scan_upload(file_obj)
    except ValidationError:
        return "SCAN_INVALID"
    return None


@transaction.atomic
def apply_transition(
    contract_id: int,
    action: str,
    actor: Optional[CustomUser],
    *,
    reason: str = "",
    note: str = "",
    scan=None,
    channel: str = "",
    counterparty_person: str = "",
) -> Tuple[Optional[Contract], Optional[str]]:
    """Перевести договор по действию `action` из `TRANSITIONS`; `(договор, None)` или `(None, код ошибки)`.

    Коды: `CONTRACT_NOT_FOUND`, `MEMBER_REQUIRED_FOR_ACTION` (нет права `contract.*` в своей компании),
    `CONTRACT_TRANSITION_NOT_ALLOWED` (статус не тот), `REASON_REQUIRED` (отклонение без причины), `SCAN_REQUIRED` и
    `SCAN_INVALID` (скан не приложен или не PDF/изображение, больше лимита, подделана сигнатура), `CHANNEL_INVALID` и
    `COUNTERPARTY_PERSON_REQUIRED` («Согласован клиентом» без канала или лица со стороны клиента, A2 волны 18a),
    `CONTRACT_VISAS_REQUIRED` (отправка клиенту до сбора виз, Х-1: HTTP 409, слова — `send_blocker`).
    """
    transition = TRANSITIONS.get(action)
    if transition is None:
        return None, "CONTRACT_TRANSITION_NOT_ALLOWED"
    contract = (
        Contract.objects.select_for_update(of=("self",))
        .select_related("deal__company", "status", "currency", "quote")
        .filter(pk=contract_id)
        .first()
    )
    if contract is None:
        return None, "CONTRACT_NOT_FOUND"
    if not (is_staff(actor) and may(actor, transition.permission)):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    before = _status_code(contract) or ""
    if before not in transition.sources:
        return None, "CONTRACT_TRANSITION_NOT_ALLOWED"
    if action == "send_to_client":
        blocker = send_blocker(contract)  # одна проверка: шаблон (ДОК-10) и визы (Х-1)
        if blocker:
            return None, blocker["code"] if blocker["code"] in TEMPLATE_BLOCKER_WORDS else "CONTRACT_VISAS_REQUIRED"
    reason = (reason or "").strip()
    note = (note or "").strip()
    if transition.needs_reason and not reason:
        return None, "REASON_REQUIRED"
    if transition.needs_file:
        # ПК-1: «Подписан» — скан ИЛИ заметка (скан не обязателен); заметка без скана — слово менеджера в журнале
        if scan is not None or not note:
            error = _check_scan(scan)
            if error:
                return None, error
    on_behalf, error = _on_behalf_note(transition, channel, counterparty_person)
    if error:
        return None, error

    from integration.services import document_events, events

    was_sent = contract_sent_to_client(contract)
    now = timezone.now()
    fields = ["status", "updated_at"]
    with document_events.watch_document_issue(
        "contract", contract
    ):  # `document.created` — когда договор стал виден клиенту
        contract.status = _status_row(transition.target)
        if action == "client_agreed":
            contract.client_signed_at = now
            fields.append("client_signed_at")
        elif action == "revise":
            # Новая редакция: прежние подписи (клиента и продавца) не переносятся.
            contract.client_signed_at = None
            contract.client_signer = None
            contract.manager_signed_at = None
            contract.manager_signer = None
            fields += ["client_signed_at", "client_signer", "manager_signed_at", "manager_signer"]
            fields += _drop_company_stamp(contract)
        elif action == "attach_scan":
            if scan is not None:
                contract.signed_file = scan
                fields.append("signed_file")
            contract.manager_signed_at = now
            if contract.client_signed_at is None:
                contract.client_signed_at = now
                fields.append("client_signed_at")
            fields.append("manager_signed_at")
        contract.save(update_fields=fields)
    _journal(contract, transition, actor, reason=reason, note=note, before=before, on_behalf=on_behalf)
    _publish(contract, actor, reason=reason)
    if action == "send_to_client" and not was_sent:
        _notify_sent(contract)
    if action == "attach_scan":
        from .contract_term import apply_at_signing

        # ДС-1: срок и последний день отказа из правила, до события «подписан». Срок считается в момент отметки
        # «подписан» (скан или заметка — ПК-1): крючок один, другого места нет.
        apply_at_signing(contract)
        events.publish_contract_signed(contract, by="both", actor=events.build_actor(actor) if actor else None)
        _after_signed(contract)
    return contract, None


def _status_row(code: str):
    from ..models import ContractStatus

    return ContractStatus.objects.get(code=code)


def _notify_sent(contract) -> None:
    from .contracts import _notify_contract_pending

    _notify_contract_pending(contract)


def _after_signed(contract) -> None:
    """Скан прикреплён: сделка → `CLOSED_WON` (запускает счёт на предоплату), уведомление сторонам, PDF не перерисовывается."""
    from .contracts import _finalize_if_signed

    if contract.supersedes_id:
        return  # новая редакция договора по уже выигранной сделке: стадию и счёт не повторяем
    _finalize_if_signed(contract)


@transaction.atomic
def create_project_contract(quote_id: int, actor: Optional[CustomUser], *, notes: str = ""):
    """«Сформировать проект договора» из принятого КП: договор в статусе `DRAFT`, клиенту не отправляется.

    Обёртка над `generate_contract_from_quote(send_to_client=False)`: те же проверки (сотрудник компании-владельца,
    КП принято — A7), тот же номер и PDF; отличие только в том, что отправляет клиенту бухгалтер отдельным
    действием.
    """
    from .contracts import generate_contract_from_quote

    return generate_contract_from_quote(quote_id, actor=actor, notes=notes, send_to_client=False)
