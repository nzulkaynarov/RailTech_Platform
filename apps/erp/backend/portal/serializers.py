"""Portal API Serializers: строго по контракту packages/contracts/openapi/erp-portal.yaml."""

from typing import Optional

from django.utils import timezone
from parties.models import Company, Contact
from portal import projections
from rest_framework import serializers

#: Лимиты контракта (`erp-portal.yaml`): `ClientRequestCreate.summary` и `Reason.reason`.
SUMMARY_MAX_LENGTH = 5000
REASON_MAX_LENGTH = 2000

_DATETIME = serializers.DateTimeField()


def iso(value) -> str:
    """Дата-время в формате ответов DRF (ISO 8601 с часовым поясом)."""
    return _DATETIME.to_representation(value)


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

    def to_representation(self, contact):
        data = super().to_representation(contact)
        # Контракт: `email` и `phone` — строка или null; пустая строка не e-mail и не телефон.
        data["email"] = projections.blank_to_none(data["email"])
        data["phone"] = projections.blank_to_none(data["phone"])
        return data


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


class MagicLinkTokenSerializer(serializers.Serializer):
    """`POST /auth/magic`: токен из фрагмента ссылки (`minLength 16`, `maxLength 512` по контракту)."""

    token = serializers.CharField(min_length=16, max_length=512, trim_whitespace=False)

    def to_internal_value(self, data):
        # DRF молча превращает число в строку; контракт требует именно строку.
        if isinstance(data, dict) and "token" in data and not isinstance(data["token"], str):
            raise serializers.ValidationError({"token": "NOT_A_STRING"})
        return super().to_internal_value(data)


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
    summary = serializers.CharField(min_length=1, max_length=SUMMARY_MAX_LENGTH)
    lines = RequestLineInSerializer(many=True, required=False, default=list)
    attachments = AttachmentRefSerializer(many=True, required=False, default=list)


class DealRefSerializer(serializers.Serializer):
    """`DealRef` контракта: сделка глазами клиента (Q-16) — номер и название вместо внутреннего id."""

    id = serializers.IntegerField(read_only=True)
    number = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()

    def get_number(self, deal) -> str:
        return projections.deal_number(deal)

    def get_title(self, deal) -> Optional[str]:
        return projections.blank_to_none(deal.title)


class RequestLineSerializer(serializers.Serializer):
    text = serializers.CharField(read_only=True)
    quantity = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()

    def get_quantity(self, line) -> Optional[str]:
        return str(line.quantity) if line.quantity is not None else None

    def get_unit(self, line) -> Optional[str]:
        return projections.blank_to_none(line.unit)


class ClientRequestSerializer(serializers.Serializer):
    """`ClientRequest`: на входе `Deal` (с prefetch `stage`, `quotes__status`, `portal_lines`, `portal_uploads`)."""

    id = serializers.IntegerField(read_only=True)
    number = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    deal = serializers.SerializerMethodField()
    deal_id = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)
    lines = RequestLineSerializer(source="portal_lines", many=True, read_only=True)
    attachments = serializers.SerializerMethodField()

    def get_number(self, deal) -> str:
        return projections.request_number(deal)

    def get_status(self, deal) -> str:
        return projections.request_status(deal)

    def get_summary(self, deal) -> str:
        summary = getattr(deal, "portal_summary", None)  # полный текст клиента (до 5000); у чужих путей — название
        return summary.text if summary else deal.title or f"Запрос #{deal.pk}"

    def get_source(self, deal) -> str:
        return projections.request_source(deal)

    def _became_deal(self, deal) -> bool:
        # Запрос, по которому ещё ничего не произошло, — не сделка (Q-16): `deal` и `deal_id` пусты.
        return projections.request_status(deal) != "new"

    def get_deal(self, deal) -> Optional[dict]:
        return DealRefSerializer(deal).data if self._became_deal(deal) else None

    def get_deal_id(self, deal) -> Optional[int]:
        return deal.pk if self._became_deal(deal) else None

    def get_attachments(self, deal) -> list:
        return [{"upload_id": str(upload.upload_id), "name": upload.name} for upload in deal.portal_uploads.all()]


class DealLinkedSerializer(serializers.Serializer):
    """Общее: `deal: DealRef` + устаревший `deal_id` рядом (снимается в FIX-24)."""

    deal = DealRefSerializer(read_only=True)
    deal_id = serializers.IntegerField(read_only=True)


class QuoteListItemSerializer(DealLinkedSerializer):
    id = serializers.IntegerField(read_only=True)
    number = serializers.SerializerMethodField()
    version = serializers.IntegerField(read_only=True)
    status = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    valid_until = serializers.DateField(read_only=True, allow_null=True)
    sent_at = serializers.SerializerMethodField()

    def get_number(self, quote) -> str:
        return projections.quote_number(quote)

    def get_status(self, quote) -> str:
        return projections.quote_status(quote)

    def get_total(self, quote) -> dict:
        return projections.money(quote.total_incl_vat, projections.currency_code(quote.quote_currency))

    def get_sent_at(self, quote) -> str:
        return iso(projections.quote_sent_at(quote))


class QuoteLineSerializer(serializers.Serializer):
    line_no = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["item", "section", "note", "stage"])
    title = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    quantity = serializers.CharField(allow_null=True)
    unit = serializers.CharField(allow_null=True)
    unit_price = serializers.DictField(allow_null=True)
    total = serializers.DictField(allow_null=True)
    promised_date = serializers.DateField(allow_null=True)


class QuoteSerializer(QuoteListItemSerializer):
    lines = serializers.SerializerMethodField()
    public_url = serializers.SerializerMethodField()
    pdf_document_id = serializers.SerializerMethodField()
    rejected_reason = serializers.SerializerMethodField()

    def get_lines(self, quote) -> list:
        return QuoteLineSerializer(projections.quote_lines(quote), many=True).data

    def get_public_url(self, quote) -> Optional[str]:
        return projections.quote_public_url(quote)

    def get_pdf_document_id(self, quote) -> Optional[int]:
        # PDF КП не лежит среди документов портала (`GeneratedDocument` с ним не связан) — FIX-23, QUESTIONS Q-FIX21-1.
        return None

    def get_rejected_reason(self, quote) -> Optional[str]:
        return projections.quote_rejected_reason(quote)


class QuoteAcceptSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=1, max_length=REASON_MAX_LENGTH)


class ContractSerializer(DealLinkedSerializer):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.SerializerMethodField()
    signed_by_client_at = serializers.DateTimeField(source="client_signed_at", read_only=True, allow_null=True)
    signed_by_company_at = serializers.DateTimeField(source="manager_signed_at", read_only=True, allow_null=True)
    document_id = serializers.SerializerMethodField()

    def get_status(self, contract) -> str:
        return projections.contract_status(contract)

    def get_document_id(self, contract) -> Optional[int]:
        # PDF договора в `GET /documents` отдаёт FIX-23; выдуманный id (раньше — id договора) хуже, чем `null`.
        return None


class InvoiceSerializer(DealLinkedSerializer):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    paid = serializers.SerializerMethodField()
    due_date = serializers.DateField(read_only=True, allow_null=True)
    document_id = serializers.SerializerMethodField()

    def get_status(self, invoice) -> str:
        return projections.invoice_status(invoice)

    def get_total(self, invoice) -> dict:
        return projections.money(invoice.total_incl_vat, projections.currency_code(invoice.currency))

    def get_paid(self, invoice) -> dict:
        return projections.money(invoice.amount_paid, projections.currency_code(invoice.currency))

    def get_document_id(self, invoice) -> Optional[int]:
        return None  # см. ContractSerializer.get_document_id


class ActSerializer(DealLinkedSerializer):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.SerializerMethodField()
    issued_at = serializers.SerializerMethodField()
    returned_reason = serializers.SerializerMethodField()
    document_id = serializers.SerializerMethodField()
    scan_document_id = serializers.SerializerMethodField()

    def get_status(self, act) -> str:
        return projections.act_status(act)

    def get_issued_at(self, act) -> str:
        return iso(projections.act_issued_at(act))

    def get_returned_reason(self, act) -> Optional[str]:
        return projections.blank_to_none(act.rejection_reason) if projections.act_status(act) == "returned" else None

    def get_document_id(self, act) -> Optional[int]:
        return None  # см. ContractSerializer.get_document_id

    def get_scan_document_id(self, act) -> Optional[int]:
        return None  # скан (`Act.signed_file`) в `GET /documents` отдаёт FIX-23, QUESTIONS Q-FIX21-1


class DeliveryLineSerializer(DealLinkedSerializer):
    """`DeliveryLine`: на входе словарь из `projections.delivery_lines` (модели строки поставки пока нет — FIX-22)."""

    id = serializers.IntegerField()
    line_no = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    quantity = serializers.CharField(allow_null=True)
    unit = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    eta = serializers.DateField(allow_null=True)
    tracking = serializers.CharField(allow_null=True)
    shipped_at = serializers.DateTimeField(allow_null=True)
    accepted_at = serializers.DateTimeField(allow_null=True)
    remark = serializers.CharField(allow_null=True)


class PortalDocumentSerializer(serializers.Serializer):
    """`Document`: на входе `GeneratedDocument` (с `template__kind`, `deal`)."""

    id = serializers.IntegerField(read_only=True)
    deal = DealRefSerializer(read_only=True, allow_null=True)
    deal_id = serializers.IntegerField(read_only=True, allow_null=True)
    kind = serializers.SerializerMethodField()
    number = serializers.CharField(read_only=True)
    date = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    size_bytes = serializers.SerializerMethodField()

    def get_kind(self, document) -> str:
        return projections.document_kind(document)

    def get_date(self, document):
        return timezone.localtime(document.created_at).date()

    def get_title(self, document) -> str:
        return document.title or f"Документ {document.number}"

    def get_file_name(self, document) -> str:
        return f"{document.number}.pdf"

    def get_size_bytes(self, document) -> int:
        return projections.document_size(document)


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
