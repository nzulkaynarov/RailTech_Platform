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
            frozenset({S.ISSUED_EXTERNAL}),
            S.SIGNED,
            "contract.sign",
            "contract.scan_attached",
            "Прикреплён скан подписанного договора",
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
    return [t.action for t in TRANSITIONS.values() if code in t.sources and may(user, t.permission) and is_staff(user)]


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


def _journal(contract, transition: Transition, actor, *, reason: str, note: str, before: str) -> None:
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
) -> Tuple[Optional[Contract], Optional[str]]:
    """Перевести договор по действию `action` из `TRANSITIONS`; `(договор, None)` или `(None, код ошибки)`.

    Коды: `CONTRACT_NOT_FOUND`, `MEMBER_REQUIRED_FOR_ACTION` (нет права `contract.*` в своей компании),
    `CONTRACT_TRANSITION_NOT_ALLOWED` (статус не тот), `REASON_REQUIRED` (отклонение без причины), `SCAN_REQUIRED` и
    `SCAN_INVALID` (скан не приложен или не PDF/изображение, больше лимита, подделана сигнатура).
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
    reason = (reason or "").strip()
    note = (note or "").strip()
    if transition.needs_reason and not reason:
        return None, "REASON_REQUIRED"
    if transition.needs_file:
        error = _check_scan(scan)
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
            contract.client_signed_at = None
            contract.client_signer = None
            fields += ["client_signed_at", "client_signer"]
        elif action == "attach_scan":
            contract.signed_file = scan
            contract.manager_signed_at = now
            if contract.client_signed_at is None:
                contract.client_signed_at = now
                fields.append("client_signed_at")
            fields += ["signed_file", "manager_signed_at"]
        contract.save(update_fields=fields)
    _journal(contract, transition, actor, reason=reason, note=note, before=before)
    _publish(contract, actor, reason=reason)
    if action == "send_to_client" and not was_sent:
        _notify_sent(contract)
    if action == "attach_scan":
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

    _finalize_if_signed(contract)


@transaction.atomic
def create_project_contract(quote_id: int, actor: Optional[CustomUser], *, notes: str = ""):
    """«Сформировать проект договора» из принятого КП: договор в статусе `DRAFT`, клиенту не отправляется.

    Обёртка над `generate_contract_from_quote(send_to_client=False)`: те же проверки (сотрудник компании-владельца,
    КП одобрено или отправлено), тот же номер и PDF; отличие только в том, что отправляет клиенту бухгалтер отдельным
    действием.
    """
    from .contracts import generate_contract_from_quote

    return generate_contract_from_quote(quote_id, actor=actor, notes=notes, send_to_client=False)
