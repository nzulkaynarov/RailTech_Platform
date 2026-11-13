"""Portal API Serializers: строго по контракту packages/contracts/openapi/erp-portal.yaml."""

import re
from decimal import Decimal
from typing import Optional

from parties.models import Company, CompanyRelationship, Contact, RelationshipStatus
from portal import projections
from portal.models import PortalSecurityEvent, PortalSession
from portal.services import act_scan
from portal.services import documents as portal_documents
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

#: Лимиты контракта (`erp-portal.yaml`): `ClientRequestCreate.summary` и `Reason.reason`.
SUMMARY_MAX_LENGTH = 5000
REASON_MAX_LENGTH = 2000
#: `QuoteCommentCreate.text` и `PaymentProofCreate.comment` (последнее — длина `PaymentConfirmation.note`).
COMMENT_MAX_LENGTH = 2000
PROOF_COMMENT_MAX_LENGTH = 500
#: Длина ИНН компании: длиннее — нельзя завести компанию (FX-1).
COMPANY_INN_MAX_LENGTH = Company._meta.get_field("inn").max_length

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
            "is_admin",
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
    country = serializers.SerializerMethodField()
    registration_number = serializers.CharField(read_only=True)
    relationship_status = serializers.SerializerMethodField()
    relationships = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "inn",
            "registration_number",
            "country",
            "legal_address",
            "bank_details",
            "language",
            "relationship_status",
            "relationships",
        ]

    def get_country(self, company):
        if isinstance(company, dict):
            c = company.get("country")
            if not c:
                return None
            if isinstance(c, dict):
                return c
            return {"code": getattr(c, "code", str(c)), "name": getattr(c, "name", "")}
        country = getattr(company, "country", None)
        if not country:
            return None
        return {
            "code": country.code,
            "name": country.name,
        }

    def get_relationship_status(self, company):
        if isinstance(company, dict):
            status = company.get("relationship_status")
            if status:
                return status
            rels = company.get("relationships") or []
            if rels and isinstance(rels[0], dict) and "status" in rels[0]:
                return rels[0]["status"]
            return RelationshipStatus.ACTIVE.value
        rel = CompanyRelationship.objects.filter(company=company).order_by("-updated_at").first()
        if rel:
            return rel.status
        if not getattr(company, "is_active", True):
            return RelationshipStatus.TERMINATED.value
        return RelationshipStatus.ACTIVE.value

    def get_relationships(self, company):
        if isinstance(company, dict):
            rels = company.get("relationships")
            if rels is not None:
                return rels
            return [
                {
                    "role": "client",
                    "kind": None,
                    "status": company.get("relationship_status", RelationshipStatus.ACTIVE.value),
                    "contract_number": None,
                    "contract_date": None,
                    "activated_at": None,
                    "suspended_at": None,
                }
            ]
        rels = list(CompanyRelationship.objects.filter(company=company).order_by("role"))
        if rels:
            return [
                {
                    "role": r.role,
                    "kind": r.kind or None,
                    "status": r.status,
                    "contract_number": r.contract_number or None,
                    "contract_date": r.contract_date.isoformat() if r.contract_date else None,
                    "activated_at": r.activated_at.isoformat() if r.activated_at else None,
                    "suspended_at": r.suspended_at.isoformat() if r.suspended_at else None,
                }
                for r in rels
            ]
        status = (
            RelationshipStatus.ACTIVE.value
            if getattr(company, "is_active", True)
            else RelationshipStatus.TERMINATED.value
        )
        return [
            {
                "role": "client",
                "kind": None,
                "status": status,
                "contract_number": None,
                "contract_date": None,
                "activated_at": None,
                "suspended_at": None,
            }
        ]


class CompanyUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=300, required=False)
    inn = serializers.CharField(max_length=20, required=False, allow_blank=True)
    registration_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    country_code = serializers.CharField(max_length=2, required=False, allow_blank=True)
    legal_address = serializers.CharField(max_length=500, required=False, allow_blank=True)
    bank_details = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    language = serializers.ChoiceField(choices=["ru", "uz", "en"], required=False)


class MeSerializer(serializers.Serializer):
    contact = TeamMemberSerializer()
    company = CompanySerializer()
    can_act = serializers.BooleanField()
    is_admin = serializers.BooleanField(default=False)
    auth_method = serializers.ChoiceField(choices=["telegram", "magic_link"])
    notifications_unread = serializers.IntegerField(min_value=0)
    roles = serializers.ListField(child=serializers.ChoiceField(choices=["client", "partner"]))
    modules = serializers.ListField(child=serializers.CharField())
    unread = serializers.IntegerField(min_value=0)  # непрочитанные ответы менеджера в чате кабинета (CHAT-1)


class TelegramAuthSerializer(serializers.Serializer):
    init_data = serializers.CharField()


class MagicLinkRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class LoginCodeSerializer(serializers.Serializer):
    """`POST /auth/code` (B-MAIL-1): адрес и 6-значный код из письма; лишние поля — не по контракту."""

    email = serializers.EmailField()
    code = serializers.RegexField(r"^\d{6}$")

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": "VALIDATION_ERROR"})
        return super().to_internal_value(data)


class PortalSessionItemSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = PortalSession
        fields = [
            "id",
            "auth_method",
            "ip_address",
            "user_agent",
            "is_current",
            "created_at",
            "last_used_at",
        ]

    def get_is_current(self, obj) -> bool:
        current_session = self.context.get("current_session")
        return bool(current_session and obj.pk == current_session.pk)


class PortalSecurityEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortalSecurityEvent
        fields = [
            "id",
            "event_type",
            "created_at",
            "actor_name",
            "actor_email",
            "ip_address",
            "user_agent",
            "target_name",
            "details",
        ]


class MagicLinkTokenSerializer(serializers.Serializer):
    """`POST /auth/magic`: токен из фрагмента ссылки (`minLength 16`, `maxLength 512` по контракту)."""

    token = serializers.CharField(min_length=16, max_length=512, trim_whitespace=False)

    def to_internal_value(self, data):
        # Контракт: `additionalProperties: false` — лишнее поле не принимается молча.
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": "VALIDATION_ERROR"})
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
    is_admin = serializers.BooleanField(default=False)
    # Контракт: `channels` обязателен, `minItems: 1`, значения `email|telegram`; доставляется только email —
    # `telegram` отвечает 422 `INVALID_CHANNEL` (FIX-23), проверка в `portal.services.invitation.invite_team_member`.
    channels = serializers.ListField(child=serializers.ChoiceField(choices=["email", "telegram"]), allow_empty=False)


class TeamMemberUpdateSerializer(serializers.Serializer):
    can_act = serializers.BooleanField(required=False)
    is_admin = serializers.BooleanField(required=False)

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": "VALIDATION_ERROR"})
        return super().to_internal_value(data)


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
    stage = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()

    def get_number(self, deal) -> str:
        return projections.deal_number(deal)

    @extend_schema_field(serializers.ChoiceField(choices=["request", "project"]))
    def get_stage(self, deal) -> str:
        return projections.deal_stage(projections.deal_number(deal))

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
    outcome = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    deal = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)
    lines = RequestLineSerializer(source="portal_lines", many=True, read_only=True)
    attachments = serializers.SerializerMethodField()

    def get_number(self, deal) -> str:
        return projections.request_number(deal)

    def get_status(self, deal) -> str:
        return projections.request_status(deal)

    def get_outcome(self, deal) -> Optional[str]:
        return projections.request_outcome(deal)

    def get_summary(self, deal) -> str:
        summary = getattr(deal, "portal_summary", None)  # полный текст клиента (до 5000); у чужих путей — название
        return summary.text if summary else deal.title or f"Запрос #{deal.pk}"

    def get_source(self, deal) -> str:
        return projections.request_source(deal)

    def _became_deal(self, deal) -> bool:
        # Запрос, по которому ещё ничего не произошло, — не сделка (Q-16): `deal` пуст.
        return projections.request_status(deal) != "new"

    def get_deal(self, deal) -> Optional[dict]:
        return DealRefSerializer(deal).data if self._became_deal(deal) else None

    def get_attachments(self, deal) -> list:
        return [{"upload_id": str(upload.upload_id), "name": upload.name} for upload in deal.portal_uploads.all()]


class DealLinkedSerializer(serializers.Serializer):
    """Общее: `deal: DealRef` (устаревший `deal_id` снят в контракте 0.3.0, FIX-25)."""

    deal = DealRefSerializer(read_only=True)


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
    comments = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    vat = serializers.SerializerMethodField()

    def get_subtotal(self, quote) -> dict:
        return projections.quote_subtotal(quote)

    def get_vat(self, quote) -> dict:
        return projections.quote_vat(quote)

    def get_lines(self, quote) -> list:
        return QuoteLineSerializer(projections.quote_lines(quote), many=True).data

    def get_public_url(self, quote) -> Optional[str]:
        return projections.quote_public_url(quote)

    def get_pdf_document_id(self, quote) -> Optional[int]:
        return portal_documents.document_id_for("quote", quote)  # null, пока КП не отправлено (QUESTIONS Q-FIX21-1)

    def get_rejected_reason(self, quote) -> Optional[str]:
        return projections.quote_rejected_reason(quote)

    def get_comments(self, quote) -> list:
        return QuoteCommentSerializer(
            quote.client_comments.select_related("author_contact", "author_user"), many=True
        ).data


class QuoteCommentSerializer(serializers.Serializer):
    """`QuoteComment`: автор — `client` (контакт клиента) или `manager` (сотрудник продавца)."""

    id = serializers.IntegerField(read_only=True)
    author = serializers.SerializerMethodField()
    author_name = serializers.SerializerMethodField()
    text = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def get_author(self, comment) -> str:
        return "manager" if comment.author_user_id else "client"

    def get_author_name(self, comment) -> Optional[str]:
        if comment.author_user_id:
            user = comment.author_user
            return projections.blank_to_none(user.get_full_name() or "")
        return projections.blank_to_none(comment.author_contact.name if comment.author_contact_id else "")


class QuoteCommentCreateSerializer(serializers.Serializer):
    """`QuoteCommentCreate`: текст 1…2000 знаков, лишних ключей нет."""

    text = StrictCharField(max_length=COMMENT_MAX_LENGTH, allow_blank=True, trim_whitespace=True)

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError("VALIDATION_ERROR")
        return super().to_internal_value(data)


class QuoteAcceptSerializer(serializers.Serializer):
    """`POST /quotes/{id}/accept`: код из `request-code` (`minLength 4`, `maxLength 12` по контракту)."""

    code = serializers.CharField(min_length=4, max_length=12)


class AcceptanceCodeSentSerializer(serializers.Serializer):
    """`AcceptanceCodeSent`: куда ушёл код (замаскированно) и сколько он действует."""

    channel = serializers.ChoiceField(choices=["telegram", "email"])
    sent_to = serializers.CharField()
    expires_in = serializers.IntegerField(min_value=1)


class ActAcceptSerializer(serializers.Serializer):
    """`ActAccept`: тело приёмки акта необязательно; `upload_id` — скан из `POST /uploads`; лишних ключей нет."""

    upload_id = serializers.CharField(required=False)

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError("VALIDATION_ERROR")
        if isinstance(data, dict) and "upload_id" in data and not isinstance(data["upload_id"], str):
            raise serializers.ValidationError({"upload_id": "NOT_A_STRING"})
        return super().to_internal_value(data)


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
    due_date = serializers.SerializerMethodField()
    document_id = serializers.SerializerMethodField()
    proofs = serializers.SerializerMethodField()

    def _days_by_seller(self) -> dict:
        # Общий на запрос кэш срока оплаты по продавцу: список счетов не ходит за настройками на каждый счёт.
        return self.context.setdefault("invoice_due_days_by_seller", {})

    def get_status(self, invoice) -> str:
        return projections.invoice_status(invoice, self._days_by_seller())

    def get_due_date(self, invoice) -> str:
        # Срок обязателен по контракту: из счёта либо по правилу выставления; счёт без срока клиенту не показывают.
        return projections.invoice_due_date(invoice, self._days_by_seller()).isoformat()

    def get_total(self, invoice) -> dict:
        return projections.money(invoice.total_incl_vat, projections.currency_code(invoice.currency))

    def get_paid(self, invoice) -> dict:
        return projections.money(invoice.amount_paid, projections.currency_code(invoice.currency))

    def get_document_id(self, invoice) -> Optional[int]:
        return portal_documents.document_id_for("invoice", invoice)

    def get_proofs(self, invoice) -> list:
        currency = projections.currency_code(invoice.currency)
        return PaymentProofSerializer(invoice.confirmations.all(), many=True, context={"currency": currency}).data


#: `PaymentProof.source` контракта ← `PaymentConfirmation.Source`.
PROOF_SOURCES = {"CABINET": "cabinet", "BOT": "bot", "EMAIL": "email", "MANUAL": "manager"}
#: `PaymentProofStatus` ← `PaymentConfirmation.Status`; отклонения в ERP пока нет (B-D24-7).
PROOF_STATUSES = {"PENDING": "pending", "CONFIRMED": "confirmed", "REJECTED": "rejected"}


class PaymentProofSerializer(serializers.Serializer):
    """`PaymentProof`: платёжка счёта глазами клиента. Заметку сотрудника (`note` платёжки не из кабинета) не отдаём."""

    id = serializers.IntegerField(read_only=True)
    status = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    submitted_at = serializers.DateTimeField(source="received_at", read_only=True)
    paid_on = serializers.DateField(source="claimed_date", read_only=True, allow_null=True)
    amount = serializers.SerializerMethodField()
    comment = serializers.SerializerMethodField()
    confirmed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    reject_reason = serializers.SerializerMethodField()

    def get_status(self, proof) -> str:
        return PROOF_STATUSES[proof.status]

    def get_source(self, proof) -> str:
        return PROOF_SOURCES[proof.source]

    def get_file_name(self, proof) -> str:
        return proof.original_name or "payment"

    def get_amount(self, proof) -> Optional[dict]:
        if proof.claimed_amount is None:
            return None
        return projections.money(proof.claimed_amount, self.context.get("currency"))

    def get_comment(self, proof) -> Optional[str]:
        return projections.blank_to_none(proof.note) if proof.source == "CABINET" else None

    def get_reject_reason(self, proof) -> Optional[str]:
        return None  # отклонения платёжки в ERP ещё нет (BACKLOG B-D24-7)


_AMOUNT_PATTERN = re.compile(r"\d{1,12}\.\d{2}", flags=re.ASCII)


class PaymentProofCreateSerializer(serializers.Serializer):
    """`PaymentProofCreate`: `upload_id` обязателен; дата не в будущем, сумма больше нуля, комментарий до 500 знаков."""

    upload_id = StrictCharField()
    paid_on = serializers.DateField(required=False, allow_null=True)
    amount = serializers.CharField(required=False, allow_null=True)
    comment = StrictCharField(required=False, allow_null=True, allow_blank=True, max_length=PROOF_COMMENT_MAX_LENGTH)

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError("VALIDATION_ERROR")
        return super().to_internal_value(data)

    def validate_paid_on(self, value):
        from django.utils import timezone

        if value is not None and value > timezone.localdate():
            raise serializers.ValidationError("VALIDATION_ERROR")
        return value

    def validate_amount(self, value):
        if value is None:
            return None
        if not isinstance(self.initial_data.get("amount"), str) or not _AMOUNT_PATTERN.fullmatch(value):
            raise serializers.ValidationError("VALIDATION_ERROR")
        amount = Decimal(value)
        if amount <= 0:
            raise serializers.ValidationError("VALIDATION_ERROR")
        return amount


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
        return act_scan.scan_document_id(act)  # документ-скан приёмки; id — из `GET /documents` (Q-FIX23-3)


class DeliveryLineSerializer(DealLinkedSerializer):
    """`DeliveryLine`: на входе `sales.DeliveryLine` (с `select_related("deal")`)."""

    id = serializers.IntegerField(read_only=True)
    line_no = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True, allow_blank=True)
    quantity = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    eta = serializers.DateField(read_only=True, allow_null=True)
    tracking = serializers.SerializerMethodField()
    shipped_at = serializers.DateTimeField(read_only=True, allow_null=True)
    accepted_at = serializers.DateTimeField(read_only=True, allow_null=True)
    remark = serializers.SerializerMethodField()

    def get_quantity(self, line) -> Optional[str]:
        return str(line.quantity) if line.quantity is not None else None

    def get_unit(self, line) -> Optional[str]:
        return projections.blank_to_none(line.unit)

    def get_tracking(self, line) -> Optional[str]:
        return projections.blank_to_none(line.tracking)

    def get_remark(self, line) -> Optional[str]:
        return projections.blank_to_none(line.remark)


class PortalDocumentSerializer(serializers.Serializer):
    """`Document`: на входе `PortalDocument` (`portal/services/documents.py`) — выпущенный документ клиента."""

    id = serializers.IntegerField(read_only=True)
    deal = serializers.SerializerMethodField()
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


class CatalogManufacturerSerializer(serializers.Serializer):
    name = serializers.CharField()
    country = serializers.CharField(allow_null=True)


class CatalogWarrantySerializer(serializers.Serializer):
    months = serializers.IntegerField(min_value=1)
    terms = serializers.CharField(allow_blank=True)


class CatalogItemDocumentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind_name = serializers.CharField()
    title = serializers.CharField()
    number = serializers.CharField(allow_blank=True)
    issued_by = serializers.CharField(allow_blank=True)
    issued_at = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)


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
    manufacturer = CatalogManufacturerSerializer(allow_null=True, required=False)
    manufacturer_part_number = serializers.CharField(allow_null=True, required=False)
    country_of_origin = serializers.CharField(allow_null=True, required=False)
    warranty = CatalogWarrantySerializer(allow_null=True, required=False)
    # Только в детальной карточке: в списке ключа нет (проекция не кладёт его без `with_documents`).
    documents = CatalogItemDocumentSerializer(many=True, required=False)


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


# ── Чат кабинета (CHAT-1, ADR-0023) ─────────────────────────────────────────────────────────────────────────────────


class _MessageContextRefSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["deal", "quote", "invoice", "act"])
    id = serializers.IntegerField(min_value=1)


class PortalMessageCreateSerializer(serializers.Serializer):
    """`PortalMessageCreate`: текст, ключ повтора Cabinet и необязательная метка документа (вид и id)."""

    text = serializers.CharField(max_length=4000, allow_blank=True, trim_whitespace=False)
    client_message_id = serializers.RegexField(r"^[A-Za-z0-9_-]{8,64}$")
    context = _MessageContextRefSerializer(required=False, allow_null=True)


class PortalMessageReadMarkSerializer(serializers.Serializer):
    last_id = serializers.IntegerField(min_value=1)


def portal_message_data(message, contact_id: int) -> dict:
    """`PortalMessage` контракта: направление, автор, «моё», текст как есть, метка документа."""
    context = None
    if message.context_kind:
        context = {"kind": message.context_kind, "id": message.context_id, "number": message.context_number}
        if message.context_kind == "deal":
            # Стадия на момент сообщения — по номеру, снятому вместе с меткой (заявка ЗВ остаётся заявкой в истории).
            context["stage"] = projections.deal_stage(message.context_number)
    return {
        "id": message.pk,
        "direction": message.direction,
        "author_name": None if message.erased else (message.author_name or None),
        "mine": message.author_contact_id is not None and message.author_contact_id == contact_id,
        "text": "" if message.erased else message.text,
        "context": context,
        "created_at": message.created_at,
        "client_message_id": message.client_message_id,
        "erased": message.erased,
    }


class DocumentVerificationSerializer(serializers.ModelSerializer):
    """`DocumentVerification` контракта (ADR-0024 §6, SIGN-VERIFY-1)."""

    class Meta:
        from portal.models import PortalDocumentVerification

        model = PortalDocumentVerification
        fields = [
            "code",
            "kind",
            "number",
            "date",
            "company_name",
            "signatory_name",
            "signatory_position",
            "signatory_basis",
            "status",
            "sha256_hash",
            "signed_at",
            "revoked_at",
            "revocation_reason",
        ]


class PartnerApplicationSerializer(serializers.ModelSerializer):
    """`PartnerApplication` контракта (ADR-0022, DECISIONS 2026-11-05, PART-ONBOARD)."""

    inn = serializers.CharField(allow_null=True, required=False)
    phone = serializers.CharField(allow_null=True, required=False)
    contract_number = serializers.CharField(allow_null=True, required=False)
    contract_date = serializers.DateField(allow_null=True, required=False)
    contract_draft_sent_at = serializers.DateTimeField(allow_null=True, required=False)
    candidate_agreed_at = serializers.DateTimeField(allow_null=True, required=False)
    candidate_notes = serializers.CharField(allow_null=True, required=False)
    has_contract_pdf = serializers.SerializerMethodField()
    rejected_reason = serializers.CharField(allow_null=True, required=False)

    class Meta:
        from parties.models import PartnerApplication

        model = PartnerApplication
        fields = [
            "id",
            "status",
            "kind",
            "categories_description",
            "company_name",
            "country",
            "inn",
            "registration_number",
            "contact_name",
            "email",
            "phone",
            "contract_number",
            "contract_date",
            "contract_draft_sent_at",
            "candidate_agreed_at",
            "candidate_notes",
            "has_contract_pdf",
            "rejected_reason",
            "created_at",
            "updated_at",
        ]

    def get_has_contract_pdf(self, obj) -> bool:
        return bool(getattr(obj, "contract_pdf", None))

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Пустые строки в nullable-полях приводим к None по OpenAPI 3.1 схеме
        for field in ("inn", "registration_number", "phone", "contract_number", "candidate_notes", "rejected_reason"):
            if not ret.get(field):
                ret[field] = None
        ret["country"] = instance.country.code if instance.country else None
        return ret


class PartnerApplicationPublicCreateSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255, min_length=1)
    country = serializers.CharField(max_length=2, allow_blank=True, allow_null=True, required=False, default="UZ")
    inn = serializers.CharField(max_length=32, allow_blank=True, allow_null=True, required=False, default="")
    registration_number = serializers.CharField(
        max_length=64, allow_blank=True, allow_null=True, required=False, default=""
    )
    kind = serializers.ChoiceField(choices=["manufacturer", "supplier", "principal", "other"], default="supplier")
    categories_description = serializers.CharField(max_length=2000, min_length=5)
    contact_name = serializers.CharField(max_length=255, min_length=1)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=32, allow_blank=True, allow_null=True, required=False, default="")
    language = serializers.ChoiceField(choices=["ru", "uz", "en"], default="ru")
    consent = serializers.BooleanField(required=True)
    website = serializers.CharField(allow_blank=True, allow_null=True, required=False, default="")

    def validate(self, attrs):
        """ИНН длиннее поля компании — 422 сразу (FX-1); у нерезидента без рег. номера он станет рег. номером."""
        inn = (attrs.get("inn") or "").strip()
        foreign_number = (attrs.get("country") or "UZ").strip().upper() != "UZ" and not (
            attrs.get("registration_number") or ""
        ).strip()
        if len(inn) > COMPANY_INN_MAX_LENGTH and not foreign_number:
            raise serializers.ValidationError({"inn": "INN_TOO_LONG"})
        return attrs

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError("CONSENT_REQUIRED")
        return value

    def validate_website(self, value):
        if value:
            raise serializers.ValidationError("HONEYPOT_DETECTED")
        return value


class PartnerApplicationClientCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["manufacturer", "supplier", "principal", "other"], default="supplier")
    categories_description = serializers.CharField(max_length=2000, min_length=5)
