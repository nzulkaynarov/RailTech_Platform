"""Фильтры биллинговых списков.

Глобально включён `DjangoFilterBackend`, но у биллинговых вьюсетов не было объявлено ни
`filterset_fields`, ни `filterset_class`. В таком случае бэкенд возвращает queryset БЕЗ
изменений — молча, без 400. То есть параметры, которые шлёт SPA, просто отбрасывались:

* `RecordPaymentDialog` запрашивает `?status=ISSUED,PARTIAL,OVERDUE`, чтобы предложить к
  оплате только живую дебиторку. Фильтр игнорировался, и в выпадающем списке оказывались
  ВСЕ счета, включая черновики, уже оплаченные и отменённые: пользователь выбирал счёт,
  который затем отклонял `record_payment`.
* `FulfillmentsPage` шлёт `?status=<код>` из выпадающего фильтра — он не работал вовсе.

`status` — внешний ключ на справочник, а SPA присылает КОД (и допускает список через
запятую), поэтому нужен явный FilterSet: `filterset_fields` такого сопоставления не умеет.
"""

from django_filters import rest_framework as filters

from crm.models import Act, Contract, Fulfillment, Invoice, Payment


class StatusCodeInFilter(filters.BaseInFilter, filters.CharFilter):
    """`?status=ISSUED,PARTIAL,OVERDUE` — один код или список кодов через запятую."""


class ContractFilter(filters.FilterSet):
    """Договоры остались без фильтра, когда его получили остальные биллинговые списки.

    Последствие видел пользователь: `BuyerAcceptedPanel` запрашивает `?deal=<id>` и берёт
    новейший не-CANCELLED договор из ответа. При игнорируемом фильтре покупатель с двумя
    сделками видел на карточке одной сделки номер договора ДРУГОЙ, а кнопка «Перейти к
    договору» открывала чужой документ.
    """

    status = StatusCodeInFilter(field_name="status__code", lookup_expr="in")

    class Meta:
        model = Contract
        fields = ["deal", "quote", "status"]


class InvoiceFilter(filters.FilterSet):
    status = StatusCodeInFilter(field_name="status__code", lookup_expr="in")

    class Meta:
        model = Invoice
        fields = ["deal", "contract", "status"]


class ActFilter(filters.FilterSet):
    status = StatusCodeInFilter(field_name="status__code", lookup_expr="in")

    class Meta:
        model = Act
        fields = ["deal", "contract", "invoice", "status"]


class PaymentFilter(filters.FilterSet):
    # У Payment нет собственной связи со сделкой — она достижима через счёт.
    deal = filters.NumberFilter(field_name="invoice__deal_id")

    class Meta:
        model = Payment
        fields = ["invoice", "deal"]


class FulfillmentFilter(filters.FilterSet):
    status = StatusCodeInFilter(field_name="status__code", lookup_expr="in")

    class Meta:
        model = Fulfillment
        fields = ["deal", "contract", "status"]
