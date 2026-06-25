from typing import Optional, Tuple

from django.db.models import QuerySet

from accounts.models import CustomUser

from ..models import Deal, Message

MAX_MESSAGE_LENGTH = 5000


def archive_messages_sync(messages: QuerySet[Message]) -> dict:
    """Move a specific set of deal-chat messages to S3 cold storage synchronously.

    Shares the JSONL format with the Celery task `crm.tasks.archive_old_messages`
    (same `_archive_path_for` + `_serialize_message`), so archives from the
    admin emergency action and the scheduled task are interleaved in the
    same daily files.

    Skips already-archived rows. Returns a summary dict:
        {'archived': <int>, 'files': <int>, 'errors': [str, ...]}
    """
    import json

    from django.core.files.base import ContentFile
    from django.utils import timezone

    from core.storage import get_private_storage

    from ..tasks import _archive_path_for, _serialize_message

    storage = get_private_storage()
    pending = list(messages.filter(is_archived=False).select_related("sender"))
    if not pending:
        return {"archived": 0, "files": 0, "errors": []}

    groups: dict = {}
    for msg in pending:
        path = _archive_path_for(msg.timestamp.date())
        groups.setdefault(path, []).append(msg)

    archived = 0
    errors: list[str] = []
    for path, group_msgs in groups.items():
        jsonl = "\n".join(json.dumps(_serialize_message(m), ensure_ascii=False) for m in group_msgs) + "\n"
        try:
            if storage.exists(path):
                with storage.open(path, "rb") as f:
                    existing = f.read().decode("utf-8")
                content = existing + jsonl
                storage.delete(path)
            else:
                content = jsonl
            storage.save(path, ContentFile(content.encode("utf-8")))
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue

        Message.objects.filter(id__in=[m.id for m in group_msgs]).update(
            is_archived=True,
            archived_at=timezone.now(),
            archive_path=path,
        )
        archived += len(group_msgs)

    return {"archived": archived, "files": len(groups) - len(errors), "errors": errors}


def user_can_access_deal_chat(user: CustomUser, deal: Deal) -> bool:
    """Platform admin, deal manager, deal client, or any active member of deal.company."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, "is_platform_admin", False):
        return True
    if deal.manager_id == user.id or deal.client_id == user.id:
        return True
    # Routed seller: a seller team whose company is a routing target of this deal may chat —
    # parity with the read-side seller_visible_deal_ids scoping (review 2026-06-25 #4: without
    # this, a routed seller could READ the thread but POST/WS/AI-reply all 403'd).
    from accounts.constants import SELLER_COMPANY_TYPES

    seller_company_ids = list(
        user.memberships.filter(
            is_active=True, can_sell=True, company__types__code__in=SELLER_COMPANY_TYPES
        ).values_list("company_id", flat=True)
    )
    if seller_company_ids and deal.seller_routings.filter(seller_company_id__in=seller_company_ids).exists():
        return True
    if deal.company_id:
        return user.memberships.filter(company_id=deal.company_id, is_active=True).exists()
    return False


def send_deal_message(user: CustomUser, deal: Deal, text: str) -> Tuple[Optional[Message], Optional[str]]:
    """
    Create a chat message for a deal after authorization + validation.
    Broadcast happens via Message post_save signal — do not group_send here.
    """
    if not user_can_access_deal_chat(user, deal):
        return None, "NOT_DEAL_MEMBER"
    clean = (text or "").strip()
    if not clean:
        return None, "EMPTY_MESSAGE"
    message = Message.objects.create(
        deal=deal,
        sender=user,
        text=clean[:MAX_MESSAGE_LENGTH],
    )

    # Audit: attach a short entry to the deal timeline so admin sees
    # who said what, without exposing the full chat log. Keep the detail
    # short; the full message stays in crm_message.
    from core.audit import log_admin_action

    preview = clean[:120] + ("…" if len(clean) > 120 else "")
    log_admin_action(
        entity_type="deal",
        entity_id=deal.id,
        action="Сообщение в чате сделки",
        detail=preview,
        actor=user,
        level="INFO",
    )
    return message, None
