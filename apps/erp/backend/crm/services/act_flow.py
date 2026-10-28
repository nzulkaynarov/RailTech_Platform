"""Акт: скан подписанного и возврат, записанные сотрудником (D2-5, SPEC-v3 §2.4 «Акт»).

Акт подписывают вне платформы (бумага или ЭДО у оператора): бухгалтер выпускает акт (`generate_act`), а после подписи
заказчиком прикрепляет скан — акт «Подписан (скан)». Если заказчик вернул акт с причиной (устно, письмом), бухгалтер
записывает возврат — акт «Возвращён» (`DRAFT` с причиной) и ждёт повторного выпуска (`reissue_act`).

Статусы ERP → слова SPEC: `DRAFT` → «Проект» (с `rejection_reason` — «Возвращён с причиной»), `ISSUED` → «Выпущен»,
`SIGNED` → «Подписан (скан)», `CANCELLED` → «Аннулирован». Право — `fulfillment.act` (во вьюхе и здесь). Переход — в
транзакции: строка акта под блокировкой, журнал (`ActivityLog`, кто и когда), событие шины (`act.accepted` /
`act.returned`). Проект «Выполнено», когда акт подписан и счета оплачены (`project_is_done`, `crm.services.projects`):
запись об этом ложится в журнал сделки один раз.
"""

from typing import Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import CustomUser
from core.validators import validate_scan_upload

from ..constants import ActStatusCode
from ..models import Act, ActivityLog
from .billing import _astatus, _locked_act, apply_act_return


def may_issue_acts(actor) -> bool:
    from accounts.services.permissions import is_seller, member_has_permission
    from core.tenant import own_company_id

    if actor is None:
        return True
    if getattr(actor, "is_superuser", False):
        return True
    return is_seller(actor) and member_has_permission(actor, own_company_id(), "fulfillment.act")


def allowed_actions(act, user) -> list:
    """Действия по акту, доступные сейчас этому пользователю (из статуса и прав): карточка проекта не считает сама."""
    if not may_issue_acts(user):
        return []
    code = act.status_code
    if code == ActStatusCode.ISSUED:
        return ["attach_scan", "return"]
    if code == ActStatusCode.DRAFT and act.rejection_reason:
        return ["reissue"]
    return []


@transaction.atomic
def attach_act_scan(act_id: int, actor: Optional[CustomUser], scan) -> Tuple[Optional[Act], Optional[str]]:
    """Прикрепить скан подписанного акта: `ISSUED` → `SIGNED`.

    Коды ошибок: `MEMBER_REQUIRED_FOR_ACTION` (нет права `fulfillment.act`), `ACT_SIGN_NOT_ALLOWED` (акт не выпущен
    или уже подписан/аннулирован), `SCAN_REQUIRED`, `SCAN_INVALID` (не PDF/изображение, больше лимита, не та сигнатура).
    """
    act = _locked_act(act_id)
    if not may_issue_acts(actor):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if act.status_code != ActStatusCode.ISSUED:
        return None, "ACT_SIGN_NOT_ALLOWED"
    if scan is None:
        return None, "SCAN_REQUIRED"
    try:
        validate_scan_upload(scan)
    except ValidationError:
        return None, "SCAN_INVALID"

    now = timezone.now()
    act.status = _astatus(ActStatusCode.SIGNED)
    act.signed_at = now
    act.acceptor_signed_at = now  # подпись заказчика поставлена вне платформы; кто именно, знает скан
    act.signed_file = scan
    act.save(update_fields=["status", "signed_at", "acceptor_signed_at", "signed_file", "updated_at"])
    from integration.services import events

    events.publish_act_event("act.accepted", act, actor=events.build_actor(actor) if actor else None)
    ActivityLog.objects.create(
        action="Акт подписан: прикреплён скан",
        detail=f"Акт {act.number} по сделке #{act.deal_id}",
        event_code="act.scan_attached",
        event_params={"number": act.number, "deal_id": act.deal_id, "manual": True, "channel": "scan"},
        user=actor,
        level="SUCCESS",
        entity_type="act",
        entity_id=act.id,
        deal=act.deal,
        company_id=act.deal.company_id,
    )
    from .deal_notifications import notify_act_signed

    transaction.on_commit(lambda: notify_act_signed(act, actor))
    from .projects import log_project_done_once

    log_project_done_once(act.deal, actor)
    return act, None


@transaction.atomic
def record_act_return(act_id: int, actor: Optional[CustomUser], reason: str) -> Tuple[Optional[Act], Optional[str]]:
    """Записать возврат акта заказчиком (устно, письмом): `ISSUED` → `DRAFT` с причиной.

    Коды: `MEMBER_REQUIRED_FOR_ACTION`, `REASON_REQUIRED`, `ACT_SIGN_NOT_ALLOWED`."""
    clean = (reason or "").strip()
    act = _locked_act(act_id)
    if not may_issue_acts(actor):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if not clean:
        return None, "REASON_REQUIRED"
    if act.status_code != ActStatusCode.ISSUED:
        return None, "ACT_SIGN_NOT_ALLOWED"
    return apply_act_return(act, actor, clean), None
