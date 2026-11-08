"""Сериализаторы раздела «Мои товары» партнёра (PART-2): форма ответа = `components.schemas` `erp-portal.yaml`.

Ключи перечислены явно, как у остальных сериализаторов портала: лишнее поле (чужая цена, закупка, поставщик) в ответ не
попадёт, даже если проекция его отдаст.
"""

from portal.serializers import MoneySerializer
from portal.services.partner_products import MAX_BATCH
from rest_framework import serializers

from catalog.models.reviews import ISSUE_FIELDS


class PartnerOfferSerializer(serializers.Serializer):
    price = MoneySerializer(allow_null=True)
    valid_from = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)
    delivery_basis = serializers.CharField(allow_null=True)
    min_order_qty = serializers.IntegerField()
    confirmed_at = serializers.DateTimeField(allow_null=True)
    freshness = serializers.ChoiceField(choices=["fresh", "expiring", "stale", "expired"])


class PartnerMissingSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()


class PartnerIssueSerializer(serializers.Serializer):
    field = serializers.ChoiceField(choices=list(ISSUE_FIELDS))
    comment = serializers.CharField()


class PartnerProductSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    brand = serializers.CharField(allow_null=True)
    manufacturer_part_number = serializers.CharField(allow_blank=True)
    category = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=["draft", "review", "returned", "published", "matched"])
    return_reason = serializers.CharField(allow_null=True)
    return_issues = PartnerIssueSerializer(many=True)
    completeness = serializers.IntegerField()
    offer = PartnerOfferSerializer(allow_null=True)
    has_pending_change = serializers.BooleanField()
    is_own = serializers.BooleanField()
    can_submit = serializers.BooleanField()
    updated_at = serializers.DateTimeField()


class PartnerReviewEntrySerializer(serializers.Serializer):
    submitted_at = serializers.DateTimeField()
    decision = serializers.ChoiceField(choices=["pending", "published", "returned", "cancelled"])
    reason = serializers.CharField(allow_blank=True)
    issues = PartnerIssueSerializer(many=True)
    decided_at = serializers.DateTimeField(allow_null=True)


class PartnerProductDetailSerializer(PartnerProductSerializer):
    description = serializers.CharField(allow_blank=True)
    hs_code = serializers.CharField(allow_blank=True)
    uom = serializers.CharField(allow_null=True)
    missing = PartnerMissingSerializer(many=True)
    history = PartnerReviewEntrySerializer(many=True)


class PartnerStatusCountsSerializer(serializers.Serializer):
    all = serializers.IntegerField()
    draft = serializers.IntegerField()
    review = serializers.IntegerField()
    returned = serializers.IntegerField()
    published = serializers.IntegerField()
    matched = serializers.IntegerField()


class PartnerAttentionSerializer(serializers.Serializer):
    expired = serializers.IntegerField()
    stale = serializers.IntegerField()
    expiring = serializers.IntegerField()


class PartnerProductPageSerializer(serializers.Serializer):
    items = PartnerProductSerializer(many=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    counts = PartnerStatusCountsSerializer()
    attention = PartnerAttentionSerializer()


class PartnerItemErrorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()


class PartnerSubmitRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=MAX_BATCH)


class PartnerSubmitResultSerializer(serializers.Serializer):
    submitted = serializers.ListField(child=serializers.IntegerField())
    errors = PartnerItemErrorSerializer(many=True)


class PartnerConfirmRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=MAX_BATCH, required=False
    )
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        # Ровно одно из двух: список карточек или «все цены компании».
        if bool(attrs.get("ids")) == bool(attrs.get("all")):
            raise serializers.ValidationError("VALIDATION_ERROR")
        return attrs


class PartnerConfirmResultSerializer(serializers.Serializer):
    confirmed = serializers.IntegerField()
    expired = serializers.IntegerField()
    errors = PartnerItemErrorSerializer(many=True)


class PriceListAcceptedSerializer(serializers.Serializer):
    task_id = serializers.CharField()


class PriceListIssueSerializer(serializers.Serializer):
    row = serializers.IntegerField()
    field = serializers.CharField(allow_null=True)
    code = serializers.CharField()
    value = serializers.CharField(allow_null=True)


class PriceListProposalSerializer(serializers.Serializer):
    row = serializers.IntegerField()
    field = serializers.CharField()


class PriceListMissingSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()


class PriceListReportSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField()
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    offers_created = serializers.IntegerField()
    offers_updated = serializers.IntegerField()
    proposal_count = serializers.IntegerField()
    proposals = PriceListProposalSerializer(many=True)
    error_count = serializers.IntegerField()
    errors = PriceListIssueSerializer(many=True)
    warning_count = serializers.IntegerField()
    warnings = PriceListIssueSerializer(many=True)
    rows_truncated = serializers.IntegerField()
    unpublishable = serializers.IntegerField()
    missing_breakdown = PriceListMissingSerializer(many=True)


class PriceListTaskSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    status = serializers.ChoiceField(choices=["pending", "running", "completed", "failed"])
    error = serializers.CharField(allow_null=True)
    report = PriceListReportSerializer(allow_null=True)


class PartnerOrderListItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=["draft", "sent", "confirmed", "received", "cancelled"])
    expected_date = serializers.DateField(allow_null=True)
    created_at = serializers.DateTimeField()
    sent_at = serializers.DateTimeField(allow_null=True)
    confirmed_at = serializers.DateTimeField(allow_null=True)
    received_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    lines_count = serializers.IntegerField()
    total_amount = serializers.CharField()
    currency = serializers.CharField()


class PartnerOrderStatusCountsSerializer(serializers.Serializer):
    all = serializers.IntegerField()
    sent = serializers.IntegerField()
    confirmed = serializers.IntegerField()
    received = serializers.IntegerField()
    cancelled = serializers.IntegerField()


class PartnerOrderPageSerializer(serializers.Serializer):
    items = PartnerOrderListItemSerializer(many=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    counts = PartnerOrderStatusCountsSerializer()


class PartnerOrderLineItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    position = serializers.IntegerField()
    product_id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_blank=True)
    quantity = serializers.IntegerField()
    received_quantity = serializers.IntegerField()
    unit_price = serializers.CharField()
    total_price = serializers.CharField()


class PartnerOrderLogItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()


class PartnerOrderDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=["draft", "sent", "confirmed", "received", "cancelled"])
    expected_date = serializers.DateField(allow_null=True)
    created_at = serializers.DateTimeField()
    sent_at = serializers.DateTimeField(allow_null=True)
    confirmed_at = serializers.DateTimeField(allow_null=True)
    received_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    cancel_reason = serializers.CharField(allow_blank=True)
    note = serializers.CharField(allow_blank=True)
    total_amount = serializers.CharField()
    currency = serializers.CharField()
    lines = PartnerOrderLineItemSerializer(many=True)
    logs = PartnerOrderLogItemSerializer(many=True)


class PartnerOrderConfirmRequestSerializer(serializers.Serializer):
    expected_date = serializers.DateField(required=False, allow_null=True)


class PartnerShipmentNoticeRequestSerializer(serializers.Serializer):
    supplier_doc = serializers.CharField(max_length=100, min_length=1)
    carrier = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    tracking_number = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class PartnerPriceRequestListItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    requested_at = serializers.DateTimeField()
    subject = serializers.CharField()
    status = serializers.ChoiceField(choices=["sent", "failed", "answered"])
    lines_count = serializers.IntegerField()
    answered_at = serializers.DateTimeField(allow_null=True)


class PartnerPriceRequestStatusCountsSerializer(serializers.Serializer):
    all = serializers.IntegerField()
    sent = serializers.IntegerField()
    answered = serializers.IntegerField()


class PartnerPriceRequestPageSerializer(serializers.Serializer):
    items = PartnerPriceRequestListItemSerializer(many=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    counts = PartnerPriceRequestStatusCountsSerializer()


class PartnerPriceRequestLineItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    quantity = serializers.IntegerField()
    unit = serializers.CharField(allow_blank=True)


class PartnerPriceRequestDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    requested_at = serializers.DateTimeField()
    subject = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    status = serializers.ChoiceField(choices=["sent", "failed", "answered"])
    answered_at = serializers.DateTimeField(allow_null=True)
    answer_note = serializers.CharField(allow_blank=True)
    lines = PartnerPriceRequestLineItemSerializer(many=True)


class PartnerPriceRequestResponseSerializer(serializers.Serializer):
    answer_note = serializers.CharField(max_length=1000, min_length=1)
