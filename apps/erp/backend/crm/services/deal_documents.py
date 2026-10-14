"""Сводка цепочки документов сделки — «карточка сделки как хаб» (Rule 8).

Зачем. Путь после подписания договора (оплата → акт → отгрузка → приёмка) на бэкенде
работал, но пользователя туда никто не вёл: `DealDetailSerializer` не отдавал ни договора,
ни счетов, ни актов, и на выигранной сделке блок документов был пуст. Найти счёт можно было
только через боковое меню.

Эталон — smart-buttons карточки заказа в Odoo (и связанные списки Salesforce): карточка
показывает счётчики-ссылки на документы цепочки и ОДНУ подсказку следующего шага.

Два инварианта, которые здесь важнее краткости:

1. **Видимость не переизобретается.** Каждый набор сужается тем же `_billing_visibility_q`,
   что и «родной» список этого типа. Иначе хаб стал бы вторым определением видимости и
   разошёлся бы с ним — ровно так проигравший со-роутед продавец увидел отгрузку победителя
   (#463). Доступ к самой сделке проверяет вызывающая вьюха через `get_object()`.

2. **Права считает сервер, а не страница.** Клиент выводил роль из `activeStatus`
   (= первый тип компании), из-за чего компания и покупатель, и продавец одновременно не
   видела продавцовских действий. Стороны здесь определяются по образцу
   `viewer_can_sign_client/manager` — по отношению зрителя К ЭТОЙ сделке.

`next_step` — ПОДСКАЗКА, а не гейт: она ничего не запрещает и никаких новых блокировок не
вводит (PRODUCT RULES §2). Реальные проверки остаются в сервисах, которые выполняют действие.
"""

from decimal import Decimal
from typing import Optional

from crm.constants import ActStatusCode, ContractStatusCode, FulfillmentStatusCode, InvoiceStatusCode

# Коды подсказки «следующий шаг» — ДЕЙСТВИЕ цепочки. Чей сейчас ход, говорит отдельный флаг
# `for_viewer`: так один код обслуживает обе стороны («оплатить счёт» / «ждём оплату»), и набор
# не разрастается парами AWAIT_*.
STEP_SIGN_CONTRACT = "SIGN_CONTRACT"
STEP_CREATE_INVOICE = "CREATE_INVOICE"
STEP_ISSUE_INVOICE = "ISSUE_INVOICE"
STEP_PAY_INVOICE = "PAY_INVOICE"
STEP_GENERATE_ACT = "GENERATE_ACT"
STEP_REISSUE_ACT = "REISSUE_ACT"
STEP_SIGN_ACT = "SIGN_ACT"
STEP_SHIP = "SHIP"
STEP_ACCEPT_DELIVERY = "ACCEPT_DELIVERY"
STEP_DONE = "DONE"

# Счета, по которым ещё ждут денег.
_OPEN_INVOICE_CODES = (InvoiceStatusCode.ISSUED, InvoiceStatusCode.PARTIAL, InvoiceStatusCode.OVERDUE)


def _money(value: Optional[Decimal]) -> str:
    """Деньги уходят строкой — как во всех биллинговых сериализаторах (DecimalField)."""
    return str(value if value is not None else Decimal("0"))


def _is_admin(user) -> bool:
    return bool(getattr(user, "is_superuser", False))


def viewer_deal_sides(user, deal, request=None) -> dict:
    """Отношение зрителя К ЭТОЙ сделке — источник правды для гейтов UI.

    Ровно то, на чём построены `viewer_can_sign_client/manager`: покупательская сторона — это
    активное членство в компании-владельце сделки с правом покупать; продавцовская — компания
    зрителя среди адресатов маршрутизации. У компании с обоими типами истинны обе.

    Одиночный случай выражен через тот же `DealSideResolver`, что обслуживает реестры: два
    определения стороны неизбежно разошлись бы, и карточка с реестром показывали бы одному
    человеку разные кнопки.
    """
    return DealSideResolver(user, request).sides_for(deal.id, deal.company_id)


class DealSideResolver:
    """Стороны зрителя сразу для МНОГИХ сделок — за два запроса на весь список.

    Нужен реестрам (счета / акты / отгрузки): там надо показать правильную кнопку в каждой
    строке, а `viewer_deal_sides` на строку дал бы N+1. Множества «мои покупательские
    компании» и «сделки, куда я пророутен как продавец» считаются один раз на запрос.

    Определение стороны здесь то же, что у `viewer_deal_sides`, — иначе реестр и карточка
    показывали бы разные кнопки одному человеку.
    """

    def __init__(self, user, request):
        from accounts.services.permissions import seller_visible_deal_ids

        anonymous = user is None or getattr(user, "is_anonymous", False)
        if anonymous:
            self.buy_company_ids = set()
            self.routed_deal_ids = set()
            return
        self.buy_company_ids = set(
            user.memberships.filter(is_active=True, can_buy=True).values_list("company_id", flat=True)
        )
        # force=True — сторона не зависит от заголовка активного контекста SPA (правило WP-1).
        self.routed_deal_ids = set(seller_visible_deal_ids(user, request, force=True) or ())

    def sides_for(self, deal_id, deal_company_id) -> dict:
        # `is_viewer` остаётся в ответе ради стабильности контракта SPA до волны 1b: плоскости
        # «оператор-наблюдатель» больше нет (M1-ERP-02), администратор = is_superuser.
        return {
            "is_buyer_side": bool(deal_company_id) and deal_company_id in self.buy_company_ids,
            "is_seller_side": deal_id in self.routed_deal_ids,
            "is_viewer": False,
        }


def _visible(model_qs, user, request, *, deal_path, seller_path):
    """Сузить набор ровно так же, как это делает «родной» список данного типа."""
    from crm.views.billing import _billing_visibility_q

    if _is_admin(user):
        return model_qs
    return model_qs.filter(
        _billing_visibility_q(user, request, deal_path=deal_path, seller_path=seller_path)
    ).distinct()


def _contracts_for(deal, user, request) -> list:
    from crm.models import Contract

    qs = Contract.objects.filter(deal_id=deal.id).select_related("status", "deal")
    return list(_visible(qs, user, request, deal_path="deal", seller_path="quote__seller_company_id"))


def _invoices_for(deal, user, request) -> list:
    """Счета сделки — ровно тем же правилом, что и `InvoiceViewSet` (включая запрет показывать
    покупателю чужой DRAFT). Правило переиспользуется, а не переписывается."""
    from crm.models import Invoice
    from crm.views.billing import invoice_visibility_q

    qs = Invoice.objects.filter(deal_id=deal.id).select_related("status").prefetch_related("payments")
    if _is_admin(user):
        return list(qs)
    return list(qs.filter(invoice_visibility_q(user, request)).distinct())


def _acts_for(deal, user, request) -> list:
    """Акты — тем же правилом, что и `ActViewSet` (владелец резолвится по всем цепочкам счёта)."""
    from crm.models import Act
    from crm.views.billing import act_visibility_q

    qs = Act.objects.filter(deal_id=deal.id).select_related("status")
    if _is_admin(user):
        return list(qs)
    return list(qs.filter(act_visibility_q(user, request)).distinct())


def _fulfillment_for(deal, user, request):
    from crm.models import Fulfillment

    qs = Fulfillment.objects.filter(deal_id=deal.id).select_related("status")
    return _visible(qs, user, request, deal_path="deal", seller_path="contract__quote__seller_company_id").first()


def _payments_for(deal, user, request) -> list:
    from crm.models import Payment

    qs = Payment.objects.filter(invoice__deal_id=deal.id).select_related("invoice")
    return list(
        _visible(
            qs,
            user,
            request,
            deal_path="invoice__deal",
            seller_path="invoice__contract__quote__seller_company_id",
        )
    )


def _live(rows, cancelled_code: str) -> list:
    """Строки без отменённых — «живая» часть цепочки."""
    return [row for row in rows if row.status_code != cancelled_code]


def _contract_payload(contract, user) -> Optional[dict]:
    if contract is None:
        return None
    from crm.services.contracts import viewer_can_sign_client, viewer_can_sign_manager

    return {
        "id": contract.id,
        "number": contract.number,
        "status": contract.status_code,
        "status_name": contract.status.name if contract.status_id else None,
        "total_amount": _money(contract.total_amount),
        "client_signed_at": contract.client_signed_at,
        "manager_signed_at": contract.manager_signed_at,
        "is_fully_signed": contract.is_fully_signed,
        # Те же подсказки, что и в ContractSerializer — чтобы хаб и страница договоров
        # показывали одну и ту же кнопку одному и тому же человеку.
        "viewer_can_sign_client": bool(viewer_can_sign_client(user, contract)),
        "viewer_can_sign_manager": bool(viewer_can_sign_manager(user, contract)),
    }


def _invoice_payload(invoice) -> dict:
    return {
        "id": invoice.id,
        "number": invoice.number,
        "status": invoice.status_code,
        "status_name": invoice.status.name if invoice.status_id else None,
        "total_incl_vat": _money(invoice.total_incl_vat),
        "amount_paid": _money(invoice.amount_paid),
        "balance_due": _money(invoice.balance_due),
        "due_date": invoice.due_date,
        "issued_at": invoice.issued_at,
    }


def _act_payload(act) -> dict:
    return {
        "id": act.id,
        "number": act.number,
        "status": act.status_code,
        "status_name": act.status.name if act.status_id else None,
        "total_amount": _money(act.total_amount),
        "signed_at": act.signed_at,
    }


def _fulfillment_payload(fulfillment) -> Optional[dict]:
    if fulfillment is None:
        return None
    status = fulfillment.status
    return {
        "id": fulfillment.id,
        "status": status.code if status else None,
        "status_name": status.name if status else None,
        "expected_delivery_date": fulfillment.expected_delivery_date,
        "shipped_at": fulfillment.shipped_at,
        "delivered_at": fulfillment.delivered_at,
        "accepted_at": fulfillment.accepted_at,
        "tracking_number": fulfillment.tracking_number,
        "carrier": fulfillment.carrier,
    }


def _step(code: str, *, for_viewer: bool, page: str, object_id=None) -> dict:
    return {"code": code, "for_viewer": bool(for_viewer), "page": page, "object_id": object_id}


def _contract_step(contract_data: dict, sides: dict) -> dict:
    """Договор ещё не подписан обеими сторонами."""
    viewer_signs = contract_data["viewer_can_sign_client"] and not contract_data["client_signed_at"]
    viewer_signs = viewer_signs or (contract_data["viewer_can_sign_manager"] and not contract_data["manager_signed_at"])
    return _step(STEP_SIGN_CONTRACT, for_viewer=viewer_signs, page="contracts", object_id=contract_data["id"])


def _invoice_step(invoices: list, sides: dict) -> Optional[dict]:
    """Шаг на участке «счёт» — или None, если счета закрыты и пора к акту."""
    if not invoices:
        return _step(STEP_CREATE_INVOICE, for_viewer=sides["is_seller_side"], page="invoices")
    draft = next((inv for inv in invoices if inv["status"] == InvoiceStatusCode.DRAFT), None)
    if draft is not None:
        return _step(STEP_ISSUE_INVOICE, for_viewer=sides["is_seller_side"], page="invoices", object_id=draft["id"])
    unpaid = next((inv for inv in invoices if inv["status"] in _OPEN_INVOICE_CODES), None)
    if unpaid is not None:
        return _step(STEP_PAY_INVOICE, for_viewer=sides["is_buyer_side"], page="invoices", object_id=unpaid["id"])
    return None


def _shipping_is_still_open(fulfillment_data: Optional[dict]) -> bool:
    """Поставка ещё не доведена до приёмки — продавцу есть что делать."""
    if fulfillment_data is None:
        return False
    return fulfillment_data["status"] not in (FulfillmentStatusCode.DELIVERED, FulfillmentStatusCode.ACCEPTED)


def _pending_act_step(acts: list, fulfillment_data: Optional[dict], sides: dict) -> Optional[dict]:
    """Выставленный акт ждёт ответа второй стороны — это приоритетный шаг цепочки.

    Документ уже на руках у контрагента, поэтому подсказка про него важнее любого следующего
    действия: пока он висит, сделка не закрывается.

    НО не для продавца, которому ещё предстоит отгрузить. Акт можно выпустить кнопкой при
    нулевой отгрузке, и как только он появлялся, подсказка переставала звать отгружать: шаг
    висел первым в цепочке и возвращался ОБЕИМ сторонам. Продавец получал «подпишите акт» и
    больше ни одного упоминания поставки — тупик тем более неприятный, что отгрузка осталась
    единственным незакрытым делом (замер 26-08, находка 13).
    """
    issued = next((act for act in acts if act["status"] == ActStatusCode.ISSUED), None)
    if issued is None:
        return None
    if sides["is_seller_side"] and not sides["is_buyer_side"] and _shipping_is_still_open(fulfillment_data):
        # Ничего не запрещаем: акт остаётся выпущенным, кнопка подписи на месте. Меняется
        # только ПОДСКАЗКА — она называет продавцу то дело, которое за ним.
        return None
    # Акт в модели несёт ОДНУ подпись, и `sign_act` не различает сторону — поэтому подсказка
    # адресована обеим. Двусторонняя модель — волна G2.
    return _step(STEP_SIGN_ACT, for_viewer=True, page="acts", object_id=issued["id"])


def _act_source_invoice_id(invoices: list) -> Optional[int]:
    """Счёт, из панели которого выпускается акт («Generate act» живёт в панели счёта).

    Предпочитаем оплаченный, затем любой выставленный, иначе первый: без `object_id`
    подсказка «Go to invoices» приводила в реестр БЕЗ открытой панели, и продавец искал
    кнопку сам (прогон глазами 17-08 — тупик на последнем шаге цепочки)."""
    for status in (InvoiceStatusCode.PAID, InvoiceStatusCode.PARTIAL, InvoiceStatusCode.ISSUED):
        found = next((inv for inv in invoices if inv["status"] == status), None)
        if found is not None:
            return found["id"]
    return invoices[0]["id"] if invoices else None


def _generate_act_step(acts: list, fulfillment_data: Optional[dict], sides: dict, invoices: list) -> Optional[dict]:
    """Пора выпустить акт — по ФАКТУ ПОСТАВКИ (G1, спека post-contract-open-questions §1).

    Раньше подсказка появлялась по оплаченному счёту. Бенчмарк показал, что оплата не является
    триггером закрывающего документа ни в одном эталоне: в Odoo он привязан к валидации отгрузки,
    в SAP — к приёмке получателем, а IFRS 15 / ASC 606 признают выручку по передаче контроля, а
    не по факту платежа. Поэтому условие — состоявшаяся поставка.
    """
    # Аннулированный акт цепочку НЕ закрывает: он мёртв, закрывающего документа у сделки нет.
    # Раньше подсказку гасило наличие ЛЮБОГО акта, и система рапортовала «Завершено» по сделке
    # без единого живого закрывающего документа (замер 24-08).
    live_acts = [act for act in acts if act["status"] != ActStatusCode.CANCELLED]
    rejected = next((act for act in live_acts if act["status"] == ActStatusCode.DRAFT), None)
    if rejected is not None:
        # Заказчик вернул акт с причиной — следующий шаг исполнителя именно этот документ,
        # а не второй рядом (иначе продавец шёл на счета и плодил дубль).
        return _step(
            STEP_REISSUE_ACT,
            for_viewer=sides["is_seller_side"],
            page="acts",
            object_id=rejected["id"],
        )
    if live_acts or fulfillment_data is None:
        return None
    delivered = fulfillment_data["status"] in (FulfillmentStatusCode.DELIVERED, FulfillmentStatusCode.ACCEPTED)
    if not delivered:
        return None
    return _step(
        STEP_GENERATE_ACT,
        for_viewer=sides["is_seller_side"],
        page="invoices",
        object_id=_act_source_invoice_id(invoices),
    )


def _fulfillment_step(fulfillment_data: Optional[dict], sides: dict) -> Optional[dict]:
    if fulfillment_data is None:
        return None
    status = fulfillment_data["status"]
    if status == FulfillmentStatusCode.ACCEPTED:
        return None
    if status == FulfillmentStatusCode.DELIVERED:
        return _step(
            STEP_ACCEPT_DELIVERY,
            for_viewer=sides["is_buyer_side"],
            page="fulfillments",
            object_id=fulfillment_data["id"],
        )
    return _step(STEP_SHIP, for_viewer=sides["is_seller_side"], page="fulfillments", object_id=fulfillment_data["id"])


def _next_step(*, contract_data, invoices, acts, fulfillment_data, sides) -> Optional[dict]:
    """Одна подсказка «что дальше» по фактическому состоянию цепочки.

    Порядок: договор → (выставленный акт, если висит) → счёт и оплата → отгрузка и приёмка →
    выпуск акта по факту поставки. Закрывающий документ стоит ПОСЛЕ поставки, а не после
    оплаты — см. `_generate_act_step`. Счёт при этом идёт раньше отгрузки: у нас он рождается
    из договора, и предоплата — обычное условие поставки в этом рынке.

    Ничего не запрещает: это подпись к кнопке, а не гейт.
    """
    if contract_data is None:
        return None
    if not contract_data["is_fully_signed"]:
        return _contract_step(contract_data, sides)
    for step in (
        _pending_act_step(acts, fulfillment_data, sides),
        _invoice_step(invoices, sides),
        _fulfillment_step(fulfillment_data, sides),
        _generate_act_step(acts, fulfillment_data, sides, invoices),
    ):
        if step is not None:
            return step
    return _step(STEP_DONE, for_viewer=False, page="fulfillments")


def deal_execution_is_complete(deal) -> bool:
    """Исполнение сделки закрыто целиком: акт подписан, счёт оплачен, поставка принята.

    O4 (18-08): «выиграна» и «исполнена» — РАЗНЫЕ шкалы. У Odoo продажная шкала кончается
    нейтральным «Sales Order», а рядом живут `invoice_status` и `delivery_status`; Salesforce
    и HubSpot добиваются того же переносом исполнения на другой объект. У нас `CLOSED_WON`
    ставится при подписании договора — до оплаты и поставки, поэтому слово «Завершено»
    отдаётся ТОЛЬКО этому предикату (аналог ручного Lock у Odoo — терминальное состояние).

    Считается по фактам, без нового поля: одна функция для списка сделок и для витрин.
    """
    from crm.constants import ActStatusCode, FulfillmentStatusCode, InvoiceStatusCode

    invoices = list(deal.invoices.all())
    if not invoices or any(inv.status_code != InvoiceStatusCode.PAID for inv in invoices):
        return False
    # Аннулированный акт — не незакрытый документ, а отменённый: он не должен вечно держать
    # сделку в «не завершено». Считаем только живые, но хотя бы один подписанный обязан быть.
    acts = [act for act in deal.acts.all() if act.status_code != ActStatusCode.CANCELLED]
    if not acts or any(act.status_code != ActStatusCode.SIGNED for act in acts):
        return False
    fulfillment = getattr(deal, "fulfillment", None)
    # У Fulfillment статус — FK-справочник без свойства `status_code` (в отличие от счёта и акта).
    fulfillment_code = getattr(getattr(fulfillment, "status", None), "code", None)
    if fulfillment_code != FulfillmentStatusCode.ACCEPTED:
        return False
    return True


def deal_document_hub(deal, user, request) -> dict:
    """Цепочка документов сделки + права зрителя + подсказка следующего шага.

    Доступ к самой сделке проверяет вызывающая вьюха (`get_object()`); здесь дополнительно
    сужается КАЖДЫЙ набор — у сделки с несколькими продавцами документы победителя не должны
    попасть проигравшему.
    """
    sides = viewer_deal_sides(user, deal, request)

    contracts = _contracts_for(deal, user, request)
    live_contracts = _live(contracts, ContractStatusCode.CANCELLED)
    contract = live_contracts[0] if live_contracts else (contracts[0] if contracts else None)

    invoices = _live(_invoices_for(deal, user, request), InvoiceStatusCode.CANCELLED)
    acts = _live(_acts_for(deal, user, request), ActStatusCode.CANCELLED)
    fulfillment = _fulfillment_for(deal, user, request)
    payments = _payments_for(deal, user, request)

    contract_data = _contract_payload(contract, user)
    invoice_data = [_invoice_payload(inv) for inv in invoices]
    act_data = [_act_payload(act) for act in acts]
    fulfillment_data = _fulfillment_payload(fulfillment)

    return {
        "deal": deal.id,
        "stage_code": deal.stage.code if deal.stage_id else None,
        "contract": contract_data,
        "invoices": invoice_data,
        "acts": act_data,
        "fulfillment": fulfillment_data,
        "payments_count": len(payments),
        "payments_total": _money(sum((payment.amount for payment in payments), Decimal("0"))),
        # Сторона зрителя ПО ЭТОЙ сделке. Это не полное право на действие: сервис,
        # выполняющий действие, дополнительно проверит подписку и стадию — и честно
        # откажет бизнес-кодом. Клиенту эти флаги нужны, чтобы не показывать чужих кнопок.
        "viewer": sides,
        "next_step": _next_step(
            contract_data=contract_data,
            invoices=invoice_data,
            acts=act_data,
            fulfillment_data=fulfillment_data,
            sides=sides,
        ),
    }
