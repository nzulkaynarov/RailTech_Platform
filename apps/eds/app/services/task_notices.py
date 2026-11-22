"""Сигнал о задаче «Главной» (ГЛ-2): задача пришла к сотруднику — одно уведомление, не заглядывая в очередь.

Строка очереди BFF и сигнал выводятся из одного факта: текущий шаг маршрута (или письмо без резолюции) сейчас ждёт
этого человека. EDS публикует `document.notice_requested`, CRM кладёт строку в колокольчик и пишет в Telegram
(решения — по настройке сотрудника). Один раз на приход: ключ — шаг маршрута или письмо, повтор доставки и повторный
вызов не создают второго уведомления.

* КП (`approve_quote`) — держателям права решения; служебка, заявление, отчёт — шаг «Директор» (`approve_memo`) или
  «Бухгалтер» (`pay_memo`); коммерческий документ — виза (`visa_commercial`) и «Подписать» (`sign_commercial`);
* автору возвращённый документ — `rework_document` (только колокольчик, решение за автором);
* входящее письмо без резолюции — адресату (`resolve_letter`).
Тот, кто сам запустил шаг, о нём не уведомляется; автор не получает шаг по своему документу, если есть другой
держатель права (как `access.step_open_to`).
"""

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import any_, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRoute, ApprovalStep, Document, Employee, Letter
from app.schemas.approvals import ApprovalTemplate
from app.services import document_notices
from app.services.people import load_directory

VISA_PERMISSIONS = frozenset({"approvals.visa_finance", "approvals.visa_legal"})
PAYMENT_PERMISSION = "payments.confirm"


async def _holders(session: AsyncSession, permission: str) -> list[int]:
    found = await session.execute(
        select(Employee.crm_user_id)
        .where(Employee.is_active.is_(True), literal(permission) == any_(Employee.permissions_eds))
        .order_by(Employee.crm_user_id)
    )
    return [int(i) for i in found.scalars()]


async def _step_recipients(
    session: AsyncSession, step: ApprovalStep, document: Document | None, actor_id: int | None
) -> list[int]:
    """Кому шаг «мой»: названный сотрудник или любой держатель права; без автора (если есть другой держатель) и без
    того, кто запустил шаг."""
    if step.assignee_crm_user_id is not None:
        people = [step.assignee_crm_user_id]
    else:
        people = await _holders(session, step.assignee_permission or "")
        if document is not None and document.author_crm_user_id in people and len(people) > 1:
            people.remove(document.author_crm_user_id)
    return [uid for uid in people if uid != actor_id]


def _kind(route: ApprovalRoute, step: ApprovalStep) -> str:
    if route.template == ApprovalTemplate.QUOTE.value:
        return "approve_quote"
    if route.template == ApprovalTemplate.SIGNING.value:
        return "visa_commercial" if step.assignee_permission in VISA_PERMISSIONS else "sign_commercial"
    return "pay_memo" if step.assignee_permission == PAYMENT_PERMISSION else "approve_memo"


async def step_arrived(
    session: AsyncSession,
    bus: AsyncBus,
    route: ApprovalRoute,
    document: Document | None,
    step: ApprovalStep,
    *,
    actor_id: int | None,
) -> None:
    """Шаг маршрута стал текущим: сигнал тем, кто его решает. Вызывается при открытии круга и при переходе к шагу."""
    kind = _kind(route, step)
    recipients = await _step_recipients(session, step, document, actor_id)
    key = f"approval:{route.id}:s{step.index}:{kind}"
    if route.template == ApprovalTemplate.QUOTE.value:
        number = route.quote_number or str(route.id)
        title = f"КП на одобрение: {number} v{route.quote_version}"[:200]
        subtitle = route.deal_number
    elif route.template == ApprovalTemplate.SIGNING.value:
        snap = route.signing_snapshot or {}
        number = str(snap.get("number") or route.id)
        title = (f"Подпишите: {route.title}" if kind == "sign_commercial" else f"Нужна виза: {route.title}")[:200]
        subtitle = step.label if kind == "visa_commercial" else None
    else:
        if document is None:
            return
        name = document_notices.name_of(document)
        verb = "Примите к оплате" if kind == "pay_memo" else "Согласуйте"
        directory = await load_directory(session, [document.author_crm_user_id])
        await document_notices.publish_notice(
            session,
            bus,
            kind=kind,
            key=key,
            recipients=recipients,
            title=f"{verb}: {name}",
            subtitle=f"{document.subject} · {directory.name(document.author_crm_user_id)}",
            actor_id=actor_id,
            document=document,
        )
        return
    await document_notices.publish_notice(
        session,
        bus,
        kind=kind,
        key=key,
        recipients=recipients,
        title=title,
        subtitle=subtitle,
        actor_id=actor_id,
        approval={"eds_approval_id": str(route.id), "template": route.template, "number": number[:64]},
    )


async def returned_to_author(
    session: AsyncSession,
    bus: AsyncBus,
    route: ApprovalRoute,
    document: Document,
    *,
    comment: str | None,
    actor_id: int,
) -> None:
    """Документ вернули на доработку: автору (колокольчик; строка «Доработать» остаётся в «Задачах»)."""
    directory = await load_directory(session, [actor_id])
    who = directory.name(actor_id)
    await document_notices.publish_notice(
        session,
        bus,
        kind="rework_document",
        key=f"approval:{route.id}:rework_document",
        recipients=[document.author_crm_user_id] if document.author_crm_user_id != actor_id else [],
        title=f"Доработайте: {document_notices.name_of(document)}",
        subtitle=f"Вернул {who}: {comment}" if comment else f"Вернул {who}",
        actor_id=actor_id,
        document=document,
    )


async def letter_awaits_resolution(
    session: AsyncSession, bus: AsyncBus, letter: Letter, *, addressee: int | None, actor_id: int | None
) -> None:
    """Входящее письмо зарегистрировано и ждёт резолюции: адресату (директору), если он не сам регистрирует."""
    sender = letter.sender_name or "отправитель не указан"
    await document_notices.publish_notice(
        session,
        bus,
        kind="resolve_letter",
        key=f"letter:{letter.id}:resolve_letter",
        recipients=[addressee] if addressee != actor_id else [],
        title=f"Наложите резолюцию: {letter.number}",
        subtitle=f"{sender} · {letter.subject}",
        actor_id=actor_id,
        letter=letter,
    )
