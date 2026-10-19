"""Portal API Serializers: строго по контракту packages/contracts/openapi/erp-portal.yaml."""

import re
from decimal import Decimal
from typing import Optional

from parties.models import Company, Contact
from portal import projections
from portal.services import documents as portal_documents
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
    # Контракт: `channels` обязателен, `minItems: 1`, значения `email|telegram`; доставляется только email —
    # `telegram` отвечает 422 `INVALID_CHANNEL` (FIX-23), проверка в `portal.services.invitation.invite_team_member`.
    channels = serializers.ListField(child=serializers.ChoiceField(choices=["email", "telegram"]), allow_empty=False)


class StrictCharField(serializers.CharField):
    """Строка по контракту: число, булево и список не превращаются в текст молча (DRF по умолчанию делает именно так)."""

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


#: Количество строки запроса: ровно то, что помещается в `PortalRequestLine.quantity` (12 знаков, три после точки).
_QUANTITY_PATTERN = re.compile(r"\d{1,9}(\.\d{1,3})?", flags=re.ASCII)


class DecimalStringField(serializers.Field):
    """`quantity` контракта: десятичная строка (`"150"`, `"0.5"`) или `null`.

    Всё остальное — 422, а не молчаливая подстановка: пустая строка, экспонента, запятая, `NaN`, ноль и минус,
    число вместо строки и значение, которое пришлось бы округлять или которое не влезает в поле базы.
    """

    default_error_messages = {"invalid": "NOT_A_DECIMAL_STRING"}

    def to_internal_value(self, data):
        if not isinstance(data, str) or not _QUANTITY_PATTERN.fullmatch(data):
            self.fail("invalid")
        value = Decimal(data)
        if value <= 0:
            self.fail("invalid")
        return value

    def to_representation(self, value):
        return format_quantity(value)


def format_quantity(value) -> Optional[str]:
    """Десятичная строка количества без хвостовых нулей хранилища: `150.000` → `"150"`, `0.500` → `"0.5"`."""
    if value is None:
        return None
    return format(Decimal(value).normalize(), "f")


class RequestLineInSerializer(serializers.Serializer):
    text = StrictCharField(min_length=1, max_length=1000)
    quantity = DecimalStringField(required=False, allow_null=True)
    unit = StrictCharField(required=False, allow_null=True, allow_blank=True, max_length=50)


class AttachmentRefSerializer(serializers.Serializer):
    upload_id = StrictCharField(max_length=64)
    name = StrictCharField(max_length=255)


class ClientRequestCreateSerializer(serializers.Serializer):
    summary = StrictCharField(min_length=1, max_length=SUMMARY_MAX_LENGTH)
    lines = RequestLineInSerializer(many=True, required=False, allow_empty=True, default=list)
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
        return format_quantity(line.quantity)

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
        return portal_documents.document_id_for("quote", quote)  # null, пока КП не отправлено (QUESTIONS Q-FIX21-1)

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
        return portal_documents.document_id_for("contract", contract)  # id из `GET /documents`; null — документа нет


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
        return portal_documents.document_id_for("invoice", invoice)


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
        return portal_documents.document_id_for("act", act)

    def get_scan_document_id(self, act) -> Optional[int]:
        return None  # скан (`Act.signed_file`) — зона FIX-22; вида документа «скан акта» в списке нет (QUESTIONS Q-FIX23-3)


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
    """`Document`: на входе `PortalDocument` (`portal/services/documents.py`) — выпущенный документ клиента."""

    id = serializers.IntegerField(read_only=True)
    deal = serializers.SerializerMethodField()
    deal_id = serializers.IntegerField(read_only=True, allow_null=True)
    kind = serializers.CharField(read_only=True)
    number = serializers.CharField(read_only=True)
    date = serializers.DateField(read_only=True)
    title = serializers.CharField(read_only=True)
    file_name = serializers.CharField(read_only=True)
    size_bytes = serializers.SerializerMethodField()

    def get_deal(self, document) -> Optional[dict]:
        return DealRefSerializer(document.deal).data if document.deal is not None else None

    def get_size_bytes(self, document) -> int:
        return portal_documents.file_size(document)


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
