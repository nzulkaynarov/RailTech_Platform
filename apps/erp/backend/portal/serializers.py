"""Portal API Serializers: строго по контракту packages/contracts/openapi/erp-portal.yaml."""

from parties.models import Company, Contact
from rest_framework import serializers


class MoneySerializer(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()


class TeamMemberSerializer(serializers.ModelSerializer):
    has_telegram = serializers.BooleanField(read_only=True)
    preferred_channel = serializers.CharField(default="both")

    class Meta:
        model = Contact
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "has_telegram",
            "language",
            "preferred_channel",
            "can_act",
            "is_primary",
            "invited_at",
            "last_login_at",
        ]


class CompanySerializer(serializers.ModelSerializer):
    bank_details = serializers.CharField(source="formatted_bank_details", read_only=True)

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "inn",
            "legal_address",
            "bank_details",
            "language",
        ]


class CompanyUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=300, required=False)
    inn = serializers.CharField(max_length=20, required=False, allow_blank=True)
    legal_address = serializers.CharField(max_length=500, required=False, allow_blank=True)
    bank_details = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    language = serializers.ChoiceField(choices=["ru", "uz", "en"], required=False)


class MeSerializer(serializers.Serializer):
    contact = TeamMemberSerializer()
    company = CompanySerializer()
    can_act = serializers.BooleanField()
    auth_method = serializers.ChoiceField(choices=["telegram", "magic_link"])


class TelegramAuthSerializer(serializers.Serializer):
    init_data = serializers.CharField()


class MagicLinkRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class TeamInviteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    language = serializers.ChoiceField(choices=["ru", "uz", "en"], default="ru")
    can_act = serializers.BooleanField(default=False)
    channels = serializers.ListField(
        child=serializers.ChoiceField(choices=["email", "telegram"]),
        required=False,
        default=list,
    )


class RequestLineInSerializer(serializers.Serializer):
    text = serializers.CharField(min_length=1, max_length=1000)
    quantity = serializers.CharField(required=False, allow_null=True)
    unit = serializers.CharField(required=False, allow_null=True)


class AttachmentRefSerializer(serializers.Serializer):
    upload_id = serializers.CharField()
    name = serializers.CharField()


class ClientRequestCreateSerializer(serializers.Serializer):
    summary = serializers.CharField(min_length=1, max_length=500)
    lines = RequestLineInSerializer(many=True, required=False, default=list)
    attachments = AttachmentRefSerializer(many=True, required=False, default=list)


class ClientRequestSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=["new", "in_progress", "quoted", "closed"])
    summary = serializers.CharField()
    source = serializers.CharField(default="cabinet")
    deal_id = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()
    lines = RequestLineInSerializer(many=True, required=False)
    attachments = AttachmentRefSerializer(many=True, required=False)


class QuoteListItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    deal_id = serializers.IntegerField()
    number = serializers.CharField()
    version = serializers.IntegerField()
    status = serializers.ChoiceField(choices=["sent", "viewed", "accepted", "rejected", "expired"])
    total = MoneySerializer()
    valid_until = serializers.DateField(allow_null=True)
    sent_at = serializers.DateTimeField()


class QuoteLineSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    line_no = serializers.IntegerField(required=False)
    kind = serializers.CharField(required=False, default="item")
    title = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.CharField()
    unit = serializers.CharField(allow_null=True)
    price = serializers.CharField(required=False, allow_null=True)
    unit_price = MoneySerializer()
    total = MoneySerializer(required=False)
    total_price = MoneySerializer(required=False)
    vat_amount = MoneySerializer(required=False)


class QuoteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    deal_id = serializers.IntegerField()
    number = serializers.CharField()
    version = serializers.IntegerField()
    status = serializers.ChoiceField(choices=["sent", "viewed", "accepted", "rejected", "expired"])
    total = MoneySerializer()
    valid_until = serializers.DateField(allow_null=True)
    sent_at = serializers.DateTimeField()
    vat_rate = serializers.CharField()
    delivery_basis = serializers.CharField(allow_blank=True, allow_null=True)
    payment_terms = serializers.CharField(allow_blank=True, allow_null=True)
    lead_time_days = serializers.IntegerField(allow_null=True)
    lines = QuoteLineSerializer(many=True)
    items = QuoteLineSerializer(many=True, required=False)


class QuoteAcceptSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=1, max_length=1000)


class ContractSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    deal_id = serializers.IntegerField()
    number = serializers.CharField()
    title = serializers.CharField()
    status = serializers.ChoiceField(
        choices=["draft", "pending_signature", "signed", "active", "completed", "cancelled"]
    )
    total = MoneySerializer()
    signed_at = serializers.DateTimeField(allow_null=True)
    document_id = serializers.IntegerField(allow_null=True)


class InvoiceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    deal_id = serializers.IntegerField()
    contract_id = serializers.IntegerField(allow_null=True)
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=["issued", "paid", "partially_paid", "overdue", "cancelled"])
    total = MoneySerializer()
    paid_amount = MoneySerializer()
    due_date = serializers.DateField(allow_null=True)
    issued_at = serializers.DateTimeField()


class ActSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    deal_id = serializers.IntegerField()
    contract_id = serializers.IntegerField(allow_null=True)
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=["issued", "signed", "returned"])
    total = MoneySerializer()
    issued_at = serializers.DateTimeField()
    signed_at = serializers.DateTimeField(allow_null=True)
    return_reason = serializers.CharField(allow_null=True, allow_blank=True)


class DeliveryLineSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    deal_id = serializers.IntegerField()
    product_name = serializers.CharField()
    quantity = serializers.CharField()
    unit = serializers.CharField()
    status = serializers.ChoiceField(choices=["pending", "in_transit", "delivered", "accepted"])
    expected_date = serializers.DateField(allow_null=True)
    tracking_number = serializers.CharField(allow_null=True, allow_blank=True)


class PortalDocumentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    deal_id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["contract", "invoice", "act", "quote", "specification", "waybill", "other"])
    title = serializers.CharField()
    number = serializers.CharField()
    date = serializers.DateField()
    file_name = serializers.CharField()
    size_bytes = serializers.IntegerField()


class AttributeItemSerializer(serializers.Serializer):
    name = serializers.CharField()
    value = serializers.CharField()


class CatalogCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    count = serializers.IntegerField()


class CatalogItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["goods", "service"])
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    unit = serializers.CharField()
    category = serializers.CharField(allow_null=True, allow_blank=True)
    category_id = serializers.IntegerField(allow_null=True, required=False)
    price = MoneySerializer(allow_null=True)
    availability = serializers.ChoiceField(choices=["in_stock", "on_order", "expected"])
    lead_time_days = serializers.IntegerField(allow_null=True)
    images = serializers.ListField(child=serializers.CharField(), default=list)
    attributes = AttributeItemSerializer(many=True, default=list)


class CatalogPageSerializer(serializers.Serializer):
    items = CatalogItemSerializer(many=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()


class PortalUploadResponseSerializer(serializers.Serializer):
    upload_id = serializers.CharField()
    name = serializers.CharField()
    mime_type = serializers.CharField(required=False)
    size_bytes = serializers.IntegerField(required=False)
