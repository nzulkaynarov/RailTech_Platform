"""Уведомления по сделке: кому и куда (Rule 8).

Собрано в одном месте, потому что «кому уходит событие» раньше решалось на каждой площадке
заново, и на пути после договора половина событий не уведомляла никого: оплату продавец не
видел вовсе, акт не порождал ни одного уведомления, просрочка доставки уходила на legacy-поле
`deal.manager`, которое у реальных сделок покупатель/продавец почти всегда пустое.

Про ссылки. У уведомления есть FK на сделку, и центр уведомлений умеет вести на карточку по
нему. Точная ссылка (`spa_link`) ставится ТОЛЬКО когда у получателя есть доступная страница
этого документа: например, реестр актов открыт только продавцу (SELLER_PAGES), поэтому
покупателю по акту точная ссылка не ставится — он попадает на карточку сделки, где акт теперь
виден в блоке цепочки.
"""

from typing import Iterable, List

from notifications.services import notify_user, spa_link


def buyer_team_user_ids(deal) -> List[int]:
    """Активные члены компании-покупателя (владельца сделки)."""
    if not deal.company_id:
        return []
    return list(deal.company.members.filter(is_active=True).values_list("user_id", flat=True))


def seller_team_user_ids(deal) -> List[int]:
    """Активные продающие члены компаний, которым разослана эта сделка."""
    from accounts.models import CustomUser

    seller_company_ids = list(deal.seller_routings.values_list("seller_company_id", flat=True))
    if not seller_company_ids:
        return []
    return list(
        CustomUser.objects.filter(
            is_active=True,
            memberships__is_active=True,
            memberships__can_sell=True,
            memberships__company_id__in=seller_company_ids,
        )
        .values_list("id", flat=True)
        .distinct()
    )


def notify_deal_users(user_ids: Iterable[int], *, deal, title: str, message: str, link: str, type_code: str) -> int:
    """Разослать одно событие сделки списку получателей. Возвращает число отправленных."""
    from accounts.models import CustomUser

    sent = 0
    for user in CustomUser.objects.filter(id__in=list(user_ids)):
        if notify_user(user=user, title=title, message=message, link=link, deal=deal, type_code=type_code):
            sent += 1
    return sent


def notify_payment_recorded(payment) -> int:
    """Продавцу — что деньги пришли. Раньше об оплате он не узнавал никак: событие писалось
    только в журнал активности."""
    invoice = payment.invoice
    deal = invoice.deal
    return notify_deal_users(
        seller_team_user_ids(deal),
        deal=deal,
        title="Оплата получена",
        message=f"По счёту {invoice.number} записана оплата на сумму {payment.amount}",
        link=spa_link("invoices", invoice.id),
        type_code="SUCCESS",
    )


def notify_act_issued(act) -> int:
    """Покупателю — что выставлен акт. Точной ссылки нет намеренно: реестр актов покупателю
    закрыт, и он попадёт на карточку сделки, где акт виден в цепочке."""
    deal = act.deal
    return notify_deal_users(
        buyer_team_user_ids(deal),
        deal=deal,
        title="Акт выставлен",
        message=f"По сделке #{deal.pk} выставлен акт {act.number} — требуется подпись",
        link="",
        type_code="INFO",
    )


def notify_act_signed(act, signer) -> int:
    """Обеим сторонам — что акт подписан; себе уведомление не шлём."""
    deal = act.deal
    recipients = set(buyer_team_user_ids(deal)) | set(seller_team_user_ids(deal))
    recipients.discard(getattr(signer, "id", None))
    return notify_deal_users(
        recipients,
        deal=deal,
        title="Акт подписан",
        message=f"Акт {act.number} по сделке #{deal.pk} подписан",
        link="",
        type_code="SUCCESS",
    )


def notify_act_rejected(act, actor, reason: str) -> int:
    """Исполнителю — что заказчик вернул акт с причиной (G2).

    Без этого отказ был бы тише согласия: акт молча уезжал обратно в черновик, и продавец
    узнавал бы об этом, только зайдя в реестр.
    """
    deal = act.deal
    recipients = set(seller_team_user_ids(deal))
    recipients.discard(getattr(actor, "id", None))
    return notify_deal_users(
        recipients,
        deal=deal,
        title="Акт отклонён заказчиком",
        message=f"Акт {act.number} по сделке #{deal.pk} возвращён на доработку: {reason}",
        link=spa_link("acts", act.id),
        type_code="WARNING",
    )


def notify_act_cancelled(act, actor, reason: str) -> int:
    """Заказчику — что исполнитель отозвал акт, и почему.

    Причина уходит вместе с уведомлением так же, как её включают в письмо об отзыве DocuSign и
    Adobe Acrobat Sign: документ исчезает из списка дел заказчика, и без основания это выглядит
    как сбой, а не как решение контрагента.
    """
    deal = act.deal
    recipients = set(buyer_team_user_ids(deal))
    recipients.discard(getattr(actor, "id", None))
    return notify_deal_users(
        recipients,
        deal=deal,
        title="Акт аннулирован исполнителем",
        message=f"Акт {act.number} по сделке #{deal.pk} отозван: {reason}",
        link="",
        type_code="WARNING",
    )


def notify_fulfillment_status(fulfillment, status_code: str, actor) -> int:
    """Смена статуса отгрузки — противоположной стороне.

    Отгружает продавец, принимает покупатель, поэтому адресат зависит от того, кто ходил:
    иначе человек получал бы уведомление о собственном действии.
    """
    from ..constants import FulfillmentStatusCode

    deal = fulfillment.deal
    buyer_side_event = status_code in (FulfillmentStatusCode.ACCEPTED, FulfillmentStatusCode.DISPUTED)
    recipients = set(seller_team_user_ids(deal)) if buyer_side_event else set(buyer_team_user_ids(deal))
    recipients.discard(getattr(actor, "id", None))
    titles = {
        FulfillmentStatusCode.SHIPPED: "Груз отгружен",
        FulfillmentStatusCode.IN_TRANSIT: "Груз в пути",
        FulfillmentStatusCode.DELIVERED: "Груз доставлен",
        FulfillmentStatusCode.ACCEPTED: "Поставка принята",
        FulfillmentStatusCode.DISPUTED: "Поставка оспорена",
    }
    title = titles.get(status_code)
    if title is None:
        return 0
    return notify_deal_users(
        recipients,
        deal=deal,
        title=title,
        message=f"Сделка #{deal.pk}: статус поставки — {title.lower()}",
        link=spa_link("fulfillments"),
        type_code="WARNING" if status_code == FulfillmentStatusCode.DISPUTED else "INFO",
    )


def notify_delivery_overdue(fulfillment) -> int:
    """Просрочка доставки — ОБЕИМ сторонам.

    Прежде уведомление уходило на `deal.manager` — legacy-поле, у реальных сделок
    покупатель/продавец почти всегда пустое, так что задача считала обработанные строки, но
    де-факто не извещала никого.
    """
    deal = fulfillment.deal
    recipients = set(buyer_team_user_ids(deal)) | set(seller_team_user_ids(deal))
    return notify_deal_users(
        recipients,
        deal=deal,
        title="Просрочка по доставке",
        message=(
            f"Сделка #{deal.pk}: ожидали {fulfillment.expected_delivery_date}, "
            f"статус — {fulfillment.status.name if fulfillment.status else '—'}"
        ),
        link=spa_link("fulfillments"),
        type_code="WARNING",
    )
