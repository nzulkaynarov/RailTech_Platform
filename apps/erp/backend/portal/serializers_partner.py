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
