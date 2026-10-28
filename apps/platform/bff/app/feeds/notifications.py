"""Центр уведомлений: ленты ERP (`erp:<id>`) и CRM (`crm:<id>`, W15-H7); вкладки — по коду события.

Лента CRM (`staff_notifications`: ответ на обращение, привязка Telegram) читается для каждого
сотрудника независимо от его разделов CRM: она общая для всех, своя у каждого. Обе ленты
сливаются по времени; непрочитанные считаются по обеим.

ERP отдаёт уведомления постранично, без счётчика непрочитанных и без фильтра `is_read`. BFF берёт
новейшие 200 (максимум страницы ERP) и страничит их сам: курсор непрозрачный (смещение),
непрочитанные считаются по этим же 200 (разрыв — docs/QUESTIONS.md, Q-PLT-14-2).
Текст — RU-вариант ERP.
"""

import base64
import binascii
from typing import Any
from urllib.parse import quote

from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed, rows
from app.feeds.models import Notification, NotificationPage, NotificationTab, ObjectRef
from app.feeds.numbers import deal_number, deal_ref, supplier_order_ref
from app.feeds.snapshot import Snapshot
from app.feeds.text import join, parse_dt, short

ERP_PAGE = 200
NOTIFICATIONS_PATH = "/api/v1/notifications/"
NOTIFICATIONS_PARAMS = {"page_size": ERP_PAGE}
DEFAULT_LIMIT = 20

# Решения: от сотрудника ждут действия.
_DECISIONS = frozenset(
    {
        "quote.submitted_for_review",
        "quote.sent_below_floor",
        "quote.approval_step_rejected",
        "deal.assigned",
        "rfq.new",
        "contract.signed_client",
        "act.rejected",
        "delivery.line_disputed",
        "fulfillment.accept_failed",
        "delivery.line_event_failed",
        "supplier_order.overdue",
    }
)
# Клиенты: что произошло с клиентом, его заявкой и документами.
_CLIENTS = (
    "quote.",
    "document.",
    "invoice.",
    "payment.",
    "act.",
    "contract.",
    "delivery.",
    "fulfillment.",
    "deal.",
    "company.",
)
# События по документам открывают проект на вкладке «Документы», по сделке — на «Карточке».
_DOCUMENT_EVENTS = (
    "quote.",
    "document.",
    "invoice.",
    "payment.",
    "act.",
    "contract.",
    "delivery.",
    "fulfillment.",
)


def tab_of(event_code: str) -> NotificationTab:
    if event_code in _DECISIONS:
        return "decisions"
    if event_code.startswith(_CLIENTS):
        return "clients"
    return "system"


def _object(row: dict[str, Any], deals: dict[int, dict[str, Any]]) -> ObjectRef | None:
    params = row.get("event_params")
    if (
        str(row.get("event_code") or "").startswith("supplier_order.")
        and isinstance(params, dict)
        and isinstance(params.get("number"), str)
    ):
        # Заказ поставщику (D2-2): заявки у уведомления нет, ведёт на карточку ЗП.
        supplier = params.get("supplier")
        return supplier_order_ref(params["number"], supplier if isinstance(supplier, str) else None)
    deal = deals.get(row["deal"]) if isinstance(row.get("deal"), int) else None
    if deal is None:
        return None
    code = str(row.get("event_code") or "")
    return deal_ref(deal, tab="documents" if code.startswith(_DOCUMENT_EVENTS) else "card")


def _subtitle(row: dict[str, Any], deals: dict[int, dict[str, Any]]) -> str | None:
    deal = deals.get(row["deal"]) if isinstance(row.get("deal"), int) else None
    if deal is not None:
        company = deal.get("company_name")
        return join(deal_number(deal), str(company) if company else None) or None
    message = short(row.get("message"), 110)
    return message if message and message != row.get("title") else None


def map_erp(row: dict[str, Any], deals: dict[int, dict[str, Any]]) -> Notification | None:
    created = parse_dt(row.get("created_at"))
    if not isinstance(row.get("id"), int) or created is None:
        return None
    obj = _object(row, deals)
    return Notification(
        id=f"erp:{row['id']}",
        tab=tab_of(str(row.get("event_code") or "")),
        title=short(row.get("title"), 160) or "Уведомление",
        subtitle=_subtitle(row, deals),
        object=obj,
        created_at=created,
        read=bool(row.get("is_read")),
    )


CRM_PATH = "/api/v1/me/notifications"
_TABS = frozenset({"decisions", "clients", "system"})


def _crm_object(row: dict[str, Any]) -> ObjectRef | None:
    """Объект уведомления CRM: пока — обращение (автору — «Мои обращения», админу — карточка)."""
    number = row.get("object_number")
    if row.get("object_kind") != "ticket" or not isinstance(number, str) or not number:
        return None
    segment = quote(number, safe="")
    if row.get("kind") == "ticket_new":
        path = f"/admin/tickets/{segment}?panel=open&tab=card"
    else:
        path = f"/help/requests/{segment}"
    return ObjectRef(kind="ticket", number=number, path=path)


def map_crm(row: dict[str, Any]) -> Notification | None:
    created = parse_dt(row.get("created_at"))
    if not isinstance(row.get("id"), int) or created is None:
        return None
    tab = row.get("tab")
    return Notification(
        id=f"crm:{row['id']}",
        tab=tab if tab in _TABS else "system",
        title=short(row.get("title"), 160) or "Уведомление",
        subtitle=short(row.get("subtitle"), 160) or None,
        object=_crm_object(row),
        created_at=created,
        read=bool(row.get("read")),
    )


async def _crm_part(feed: Feed) -> tuple[list[Notification], int]:
    """Лента CRM и число непрочитанных в ней. Не зависит от разделов CRM у сотрудника."""
    before = feed.states["crm"]
    if before == "not_applicable":
        feed.states["crm"] = (
            "ok"  # уведомления CRM есть у каждого; источник для агрегатов — прежний
        )
    payload = await feed.get("crm", CRM_PATH, ttl=SNAPSHOT_TTL_SECONDS)
    if before == "not_applicable" and feed.states["crm"] == "ok":
        feed.states["crm"] = "not_applicable"
    if not isinstance(payload, dict):
        return [], 0
    items = [n for row in rows(payload) if (n := map_crm(row)) is not None]
    unread = payload.get("unread_count")
    return items, unread if isinstance(unread, int) else sum(1 for n in items if not n.read)


def _offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(int(base64.urlsafe_b64decode(cursor.encode()).decode().removeprefix("o:")), 0)
    except (ValueError, binascii.Error):
        return 0


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


# TODO(ERP-16): `unread_count` и фильтр `is_read` в ERP; пока считаем по новейшим 200 уведомлениям.
async def list_notifications(
    feed: Feed, snap: Snapshot, tab: NotificationTab, cursor: str | None, limit: int
) -> NotificationPage:
    payload = await feed.get(
        "erp", NOTIFICATIONS_PATH, NOTIFICATIONS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS
    )
    deals = snap.deal_index
    mapped = [n for row in rows(payload) if (n := map_erp(row, deals)) is not None]
    crm_items, crm_unread = await _crm_part(feed)
    mapped = [*mapped, *crm_items]
    mapped.sort(key=lambda n: n.created_at, reverse=True)
    unread = sum(1 for n in mapped if not n.read and n.id.startswith("erp:")) + crm_unread
    shown = [n for n in mapped if tab == "all" or n.tab == tab]
    start = _offset(cursor)
    page = shown[start : start + limit]
    more = start + limit < len(shown)
    return NotificationPage(
        items=page,
        next_cursor=_cursor(start + limit) if more else None,
        unread_count=unread,
        sources=feed.sources,
    )
