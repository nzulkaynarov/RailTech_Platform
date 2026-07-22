"""Contracts / Invoices / Invoice items / Payments / Acts / Fulfillment serializers.

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor) — behaviour
unchanged.
"""

from rest_framework import serializers

from crm.models import Act, Contract, Fulfillment, Invoice, InvoiceItem, Payment


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


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    balance_due = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=2)
    # status is a FK lookup now (F5.4); keep the code string under `status` (+ name).
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()

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


class ActSerializer(serializers.ModelSerializer):
    # status is a FK lookup now (F5.4); keep the code string under `status` (+ name).
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    signed_file_url = serializers.SerializerMethodField()

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
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["number", "pdf_file", "signed_at"]

    def get_pdf_url(self, obj) -> str | None:
        return obj.pdf_file.url if obj.pdf_file else None

    def get_signed_file_url(self, obj) -> str | None:
        return obj.signed_file.url if obj.signed_file else None


class FulfillmentSerializer(serializers.ModelSerializer):
    # status is a FK lookup now (F5.4); keep emitting the code string under `status`
    # so the frontend contract is unchanged, plus the display name under status_name.
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)

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
            "notes",
            "created_at",
            "updated_at",
        ]
