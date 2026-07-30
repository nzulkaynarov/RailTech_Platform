"""Contracts / Invoices / Invoice items / Payments / Acts / Fulfillment serializers.

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor) — behaviour
unchanged.
"""

from rest_framework import serializers

from crm.constants import ActStatusCode, FulfillmentStatusCode, InvoiceStatusCode
from crm.models import Act, Contract, Fulfillment, Invoice, InvoiceItem, Payment


class ViewerSidesMixin:
    """Сторона зрителя по сделке документа — считается СЕРВЕРОМ, один раз на запрос.

    Зачем. SPA выводила роль из `activeStatus` (= первый тип компании), поэтому компания,
    которая одновременно покупает и продаёт, не видела продавцовских кнопок: «Сформировать
    акт» пряталась за `!isBuyer`, и у dual-компании с порядком типов [CLIENT, SUPPLIER]
    кнопки не было вовсе. Образец решения уже был рядом — `viewer_can_sign_client/manager`
    у договора.

    Поля-подсказки НЕ являются полным правом: подписку, KYC и стадию проверит сервис,
    выполняющий действие, и честно откажет бизнес-кодом. Их задача — не показывать человеку
    кнопок чужой стороны.
    """

    def _sides(self, deal_id, deal_company_id) -> dict:
        resolver = self.context.get("_deal_side_resolver")
        if resolver is None:
            from crm.services.deal_documents import DealSideResolver

            request = self.context.get("request")
            resolver = DealSideResolver(getattr(request, "user", None), request)
            # Кэш на весь запрос: иначе список из 20 строк дал бы 40 запросов (N+1).
            self.context["_deal_side_resolver"] = resolver
        return resolver.sides_for(deal_id, deal_company_id)


class ContractSerializer(serializers.ModelSerializer):
    client_signer_name = serializers.CharField(source="client_signer.get_full_name", read_only=True, default=None)
    manager_signer_name = serializers.CharField(source="manager_signer.get_full_name", read_only=True, default=None)
    # status is a FK lookup now (F5.4); keep emitting the code string under `status`
    # so the frontend contract is unchanged, plus the display name under status_name.
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    signed_file_url = serializers.SerializerMethodField()
    # Which side the VIEWER may sign, derived from their relationship to this contract's deal
    # (not the SPA page context) — a dual buy+sell company gets the correct button regardless of
    # the context it landed in. Mirrors the sign_contract_by_* authorization (review fix).
    viewer_can_sign_client = serializers.SerializerMethodField()
    viewer_can_sign_manager = serializers.SerializerMethodField()
    # id of the договор's LIVE (non-cancelled) invoice, or null. Lets the frontend hide the
    # «Создать инвойс» button once an invoice exists and re-enable it after a cancellation (III-3).
    invoice_id = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = [
            "id",
            "deal",
            "quote",
            "number",
            "status",
            "status_name",
            "invoice_id",
            "total_amount",
            "currency",
            "pdf_file",
            "pdf_url",
            "signed_file",
            "signed_file_url",
            "client_signer",
            "client_signer_name",
            "client_signed_at",
            "manager_signer",
            "manager_signer_name",
            "manager_signed_at",
            "viewer_can_sign_client",
            "viewer_can_sign_manager",
            "valid_from",
            "valid_until",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "number",
            "total_amount",
            "pdf_file",
            "client_signer",
            "client_signed_at",
            "manager_signer",
            "manager_signed_at",
            "created_at",
            "updated_at",
        ]

    def get_pdf_url(self, obj) -> str | None:
        return obj.pdf_file.url if obj.pdf_file else None

    def get_signed_file_url(self, obj) -> str | None:
        return obj.signed_file.url if obj.signed_file else None

    def get_invoice_id(self, obj) -> int | None:
        return obj.invoices.exclude(status__code="CANCELLED").values_list("id", flat=True).first()

    def get_viewer_can_sign_client(self, obj) -> bool:
        from crm.services.contracts import viewer_can_sign_client

        request = self.context.get("request")
        return bool(request and viewer_can_sign_client(request.user, obj))

    def get_viewer_can_sign_manager(self, obj) -> bool:
        from crm.services.contracts import viewer_can_sign_manager

        request = self.context.get("request")
        return bool(request and viewer_can_sign_manager(request.user, obj))


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields = [
            "id",
            "description",
            "quantity",
            "unit_price_excl_vat",
            "line_total_excl_vat",
            "source_quote_item",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    proof_url = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "invoice",
            "amount",
            "method",
            "paid_at",
            "reference",
            "proof_file",
            "proof_url",
            "recorded_by",
            "created_at",
        ]
        read_only_fields = ["recorded_by", "created_at"]

    def get_proof_url(self, obj) -> str | None:
        return obj.proof_file.url if obj.proof_file else None


class InvoiceSerializer(ViewerSidesMixin, serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    balance_due = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=2)
    # status is a FK lookup now (F5.4); keep the code string under `status` (+ name).
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    # Сторона зрителя ПО ЭТОМУ счёту вместо клиентской роли (см. ViewerSidesMixin).
    viewer_can_pay = serializers.SerializerMethodField()
    viewer_can_manage = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "deal",
            "contract",
            "number",
            "status",
            "status_name",
            "issued_at",
            "due_date",
            "subtotal_excl_vat",
            "vat_amount",
            "total_incl_vat",
            "amount_paid",
            "balance_due",
            "currency",
            "pdf_file",
            "pdf_url",
            "notes",
            "items",
            "payments",
            "viewer_can_pay",
            "viewer_can_manage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "number",
            "amount_paid",
            "pdf_file",
            "created_at",
            "updated_at",
        ]

    def get_pdf_url(self, obj) -> str | None:
        return obj.pdf_file.url if obj.pdf_file else None

    def get_viewer_can_pay(self, obj) -> bool:
        """Оплату записывает ПОКУПАТЕЛЬ, и только по живому выставленному счёту."""
        if obj.status_code in (InvoiceStatusCode.DRAFT, InvoiceStatusCode.CANCELLED, InvoiceStatusCode.PAID):
            return False
        return self._sides(obj.deal_id, obj.deal.company_id)["is_buyer_side"]

    def get_viewer_can_manage(self, obj) -> bool:
        """Выставить / отменить / сформировать акт — сторона ПРОДАВЦА."""
        return self._sides(obj.deal_id, obj.deal.company_id)["is_seller_side"]


class ActSerializer(ViewerSidesMixin, serializers.ModelSerializer):
    # status is a FK lookup now (F5.4); keep the code string under `status` (+ name).
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    signed_file_url = serializers.SerializerMethodField()
    # Двусторонний акт (G2): принимает ЗАКАЗЧИК, выпускает исполнитель. Раньше поле означало
    # «любая сторона может закрыть документ» — теперь оно адресное.
    viewer_can_sign = serializers.SerializerMethodField()
    viewer_can_reject = serializers.SerializerMethodField()
    issuer_signer_name = serializers.CharField(source="issuer_signer.get_full_name", read_only=True, default=None)
    acceptor_signer_name = serializers.CharField(source="acceptor_signer.get_full_name", read_only=True, default=None)

    class Meta:
        model = Act
        fields = [
            "id",
            "deal",
            "contract",
            "invoice",
            "number",
            "status",
            "status_name",
            "issued_at",
            "signed_at",
            "total_amount",
            "pdf_file",
            "pdf_url",
            "signed_file",
            "signed_file_url",
            "issuer_signer",
            "issuer_signer_name",
            "issuer_signed_at",
            "acceptor_signer",
            "acceptor_signer_name",
            "acceptor_signed_at",
            "rejection_reason",
            "viewer_can_sign",
            "viewer_can_reject",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "number",
            "pdf_file",
            "signed_at",
            "issuer_signer",
            "issuer_signed_at",
            "acceptor_signer",
            "acceptor_signed_at",
            "rejection_reason",
        ]

    def get_pdf_url(self, obj) -> str | None:
        return obj.pdf_file.url if obj.pdf_file else None

    def get_signed_file_url(self, obj) -> str | None:
        return obj.signed_file.url if obj.signed_file else None

    def _acceptor_may_answer(self, obj) -> bool:
        """Выставленный акт ждёт ответа ЗАКАЗЧИКА — принять или вернуть с причиной.

        Прежде подсказка адресовалась обеим сторонам, потому что `sign_act` сторону не
        различал: выпустивший акт мог закрыть его сам. Акт — двусторонний документ, поэтому
        отвечает вторая сторона.
        """
        if obj.status_code != ActStatusCode.ISSUED:
            return False
        return self._sides(obj.deal_id, obj.deal.company_id)["is_buyer_side"]

    def get_viewer_can_sign(self, obj) -> bool:
        return self._acceptor_may_answer(obj)

    def get_viewer_can_reject(self, obj) -> bool:
        return self._acceptor_may_answer(obj)


class FulfillmentSerializer(ViewerSidesMixin, serializers.ModelSerializer):
    # status is a FK lookup now (F5.4); keep emitting the code string under `status`
    # so the frontend contract is unchanged, plus the display name under status_name.
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    # Продвижение статуса — за продавцом, приёмка/спор — за покупателем: ровно так делит
    # стороны update_fulfillment_status. Клиент раньше решал это по activeStatus.
    viewer_can_ship = serializers.SerializerMethodField()
    viewer_can_accept = serializers.SerializerMethodField()

    class Meta:
        model = Fulfillment
        fields = [
            "id",
            "deal",
            "contract",
            "status",
            "status_name",
            "shipped_at",
            "delivered_at",
            "accepted_at",
            "expected_delivery_date",
            "tracking_number",
            "carrier",
            "viewer_can_ship",
            "viewer_can_accept",
            "notes",
            "created_at",
            "updated_at",
        ]

    def _fulfillment_sides(self, obj) -> dict:
        return self._sides(obj.deal_id, obj.deal.company_id)

    def get_viewer_can_ship(self, obj) -> bool:
        if obj.status and obj.status.code == FulfillmentStatusCode.ACCEPTED:
            return False
        return self._fulfillment_sides(obj)["is_seller_side"]

    def get_viewer_can_accept(self, obj) -> bool:
        if obj.status and obj.status.code == FulfillmentStatusCode.ACCEPTED:
            return False
        return self._fulfillment_sides(obj)["is_buyer_side"]
