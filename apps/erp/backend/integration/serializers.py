"""Integration serializers (CONTRACTS §0, §2, packages/contracts/openapi/erp-integration.yaml).

Строгая валидация и сериализация схем для API взаимодействия CRM → ERP.
"""

from __future__ import annotations

from django.core.validators import RegexValidator
from rest_framework import serializers
from sales.models import DeliveryLineStatus

from accounts.constants import Permission

from .services import stages


class MoneySerializer(serializers.Serializer):
    """Сумма денег по стандарту OpenAPI erp-integration.yaml."""

    amount = serializers.CharField()
    currency = serializers.CharField()


class ContactInSerializer(serializers.Serializer):
    crm_contact_id = serializers.IntegerField()
    name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, allow_null=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True, default="")
    telegram_user_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    language = serializers.ChoiceField(choices=["ru", "uz", "en"])
    is_primary = serializers.BooleanField()
    preferred_channel = serializers.ChoiceField(choices=["telegram", "email", "both"])


class ContactSerializer(ContactInSerializer):
    erp_contact_id = serializers.IntegerField()
    erp_company_id = serializers.IntegerField()
    cabinet_invited_at = serializers.DateTimeField(allow_null=True, required=False)


class AttachmentInSerializer(serializers.Serializer):
    name = serializers.CharField()
    url = serializers.URLField()
    content_type = serializers.CharField(required=False, allow_blank=True, default="")
    size_bytes = serializers.IntegerField(min_value=0, required=False, default=0)


class HandoffCompanyInSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=300)
    inn = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True, default="")
    segment = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True, default="")
    language = serializers.ChoiceField(choices=["ru", "uz", "en"])


class HandoffNeedInSerializer(serializers.Serializer):
    summary = serializers.CharField(max_length=5000)
    product_interest = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    attachments = serializers.ListField(child=AttachmentInSerializer(), required=False, default=list)


class HandoffOwnerInSerializer(serializers.Serializer):
    crm_user_id = serializers.IntegerField()
    name = serializers.CharField()


class HandoffConsentInSerializer(serializers.Serializer):
    given_at = serializers.DateTimeField()
    version = serializers.CharField()


class HandoffInviteInSerializer(serializers.Serializer):
    channels = serializers.ListField(child=serializers.ChoiceField(choices=["telegram", "email"]))


class HandoffRequestSerializer(serializers.Serializer):
    crm_client_id = serializers.IntegerField()
    crm_lead_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    company = HandoffCompanyInSerializer()
    contacts = serializers.ListField(child=ContactInSerializer(), min_length=1)
    need = HandoffNeedInSerializer()
    owner = HandoffOwnerInSerializer()
    consent = HandoffConsentInSerializer()
    create_request = serializers.BooleanField()
    invite = HandoffInviteInSerializer()


class HandoffResponseInviteSerializer(serializers.Serializer):
    sent_via = serializers.ListField(child=serializers.ChoiceField(choices=["telegram", "email"]))
    cabinet_url = serializers.URLField()


class HandoffResponseSerializer(serializers.Serializer):
    erp_company_id = serializers.IntegerField()
    erp_request_id = serializers.IntegerField(allow_null=True)
    invite = HandoffResponseInviteSerializer()


class DealListItemSerializer(serializers.Serializer):
    erp_deal_id = serializers.IntegerField()
    number = serializers.CharField()
    title = serializers.CharField()
    stage = serializers.ChoiceField(choices=list(stages.DEAL_STAGES))
    amount = serializers.CharField(allow_null=True)
    currency = serializers.CharField()
    next_step = serializers.CharField(allow_null=True, required=False)
    updated_at = serializers.DateTimeField()


class QuoteSummarySerializer(serializers.Serializer):
    erp_quote_id = serializers.IntegerField()
    version = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=["draft", "approval", "sent", "viewed", "accepted", "rejected", "expired"])
    public_url = serializers.URLField(allow_null=True, required=False)
    valid_until = serializers.DateField(allow_null=True, required=False)
    total = MoneySerializer(required=False)


class ContractSummarySerializer(serializers.Serializer):
    erp_contract_id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(
        choices=["draft", "sent", "signed_by_client", "signed_by_company", "signed", "cancelled"]
    )
    signed_at = serializers.DateTimeField(allow_null=True, required=False)


class InvoiceSummarySerializer(serializers.Serializer):
    erp_invoice_id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=["issued", "partially_paid", "paid", "overdue", "cancelled"])
    total = MoneySerializer()
    paid = MoneySerializer(required=False)
    due_date = serializers.DateField()


class DeliveryLineSerializer(serializers.Serializer):
    erp_deal_id = serializers.IntegerField()
    line_no = serializers.IntegerField(min_value=1)
    title = serializers.CharField()
    quantity = serializers.CharField(allow_null=True, required=False)
    unit = serializers.CharField(allow_null=True, required=False)
    status = serializers.ChoiceField(choices=[choice.value for choice in DeliveryLineStatus])
    eta = serializers.DateField(allow_null=True, required=False)
    tracking = serializers.CharField(allow_null=True, required=False)
    accepted_at = serializers.DateTimeField(allow_null=True, required=False)
    remark = serializers.CharField(allow_null=True, required=False)


class ActSummarySerializer(serializers.Serializer):
    erp_act_id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=["issued", "accepted", "returned"])
    issued_at = serializers.DateTimeField()


class DocumentSerializer(serializers.Serializer):
    erp_document_id = serializers.IntegerField()
    erp_deal_id = serializers.IntegerField(allow_null=True)
    kind = serializers.ChoiceField(choices=["quote", "contract", "invoice", "act", "waybill", "receipt", "other"])
    number = serializers.CharField()
    date = serializers.DateField()
    title = serializers.CharField()
    status = serializers.CharField()


class CompanySummarySerializer(serializers.Serializer):
    erp_company_id = serializers.IntegerField()
    crm_client_id = serializers.IntegerField()
    name = serializers.CharField()
    open_deals = DealListItemSerializer(many=True)
    last_document = DocumentSerializer(allow_null=True)
    receivables = MoneySerializer()
    next_delivery = DeliveryLineSerializer(allow_null=True)


class DealSerializer(DealListItemSerializer):
    erp_company_id = serializers.IntegerField()
    crm_client_id = serializers.IntegerField()
    quotes = QuoteSummarySerializer(many=True)
    contracts = ContractSummarySerializer(many=True)
    invoices = InvoiceSummarySerializer(many=True)
    deliveries = DeliveryLineSerializer(many=True)
    acts = ActSummarySerializer(many=True)


class DocumentLinkSerializer(serializers.Serializer):
    url = serializers.URLField()
    expires_at = serializers.DateTimeField()
    file_name = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField(min_value=0, required=False)


class CatalogItemSerializer(serializers.Serializer):
    erp_product_id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["goods", "service"])
    name = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True, default="")
    unit = serializers.CharField()
    price = MoneySerializer(allow_null=True, required=False)
    availability = serializers.ChoiceField(
        choices=["in_stock", "on_order", "expected"], allow_null=True, required=False
    )
    lead_time_days = serializers.IntegerField(allow_null=True, required=False)


class ProvisionUserRequestSerializer(serializers.Serializer):
    crm_user_id = serializers.IntegerField()
    email = serializers.EmailField()
    name = serializers.CharField()
    role = serializers.ChoiceField(choices=["admin", "backoffice"])
    # Только коды каталога прав ERP (`ErpPermission` контракта): чужой код — 422, а не молча сохранённая «роль» (S-11).
    permissions = serializers.ListField(child=serializers.ChoiceField(choices=Permission.values))
    is_active = serializers.BooleanField(default=True, required=False)


class ProvisionUserResponseSerializer(serializers.Serializer):
    erp_user_id = serializers.IntegerField()
    crm_user_id = serializers.IntegerField()


class AiUsageRowSerializer(serializers.Serializer):
    date = serializers.DateField()
    system = serializers.CharField(default="erp")
    feature = serializers.CharField()
    model = serializers.CharField()
    calls = serializers.IntegerField(min_value=0)
    input_tokens = serializers.IntegerField(min_value=0, required=False, default=0)
    output_tokens = serializers.IntegerField(min_value=0, required=False, default=0)
    cost_usd = serializers.CharField()


class HealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "degraded"])
    version = serializers.CharField()
    migrations_applied = serializers.BooleanField()
    queue_alive = serializers.BooleanField()
    checked_at = serializers.DateTimeField()


class PairingSecretField(serializers.CharField):
    """Секрет, который сгенерировала CRM: 32–512 символов URL-безопасного алфавита (контракт `PairingSecret`)."""

    def __init__(self, **kwargs):
        super().__init__(min_length=32, max_length=512, trim_whitespace=False, write_only=True, **kwargs)
        self.validators.append(RegexValidator(r"^[A-Za-z0-9_\-]+$"))


class PairingRequestSerializer(serializers.Serializer):
    """Тело `POST /pairing/accept` и `POST /pairing/rotate`: тройка секретов (M3-ERP-05)."""

    crm_to_erp_token = PairingSecretField()
    erp_to_crm_token = PairingSecretField()
    webhook_secret = PairingSecretField()

    def to_internal_value(self, data):
        # Лишние поля контракт не допускает (`additionalProperties: false`) — 422, а не молчаливое отбрасывание.
        extra = set(getattr(data, "keys", lambda: [])()) - set(self.fields)
        if extra:
            raise serializers.ValidationError("VALIDATION_ERROR")
        return super().to_internal_value(data)


class PairingAcceptedSerializer(serializers.Serializer):
    paired = serializers.BooleanField()
    paired_at = serializers.DateTimeField()
    erp_version = serializers.CharField()


class PairingRotatedSerializer(serializers.Serializer):
    rotated = serializers.BooleanField()
    rotated_at = serializers.DateTimeField()
    previous_token_valid_until = serializers.DateTimeField()
