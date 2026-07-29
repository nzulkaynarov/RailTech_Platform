"""Serializers for the N2 document-numbering-scheme editor (Settings → «Нумерация»).

Thin I/O shapes only — ALL validation/business logic lives in
``crm.services.numbering`` (Rule 8). These serializers define the request/response
contract so drf-spectacular can emit an accurate OpenAPI schema.
"""

from rest_framework import serializers

from ..models import DocumentNumberingScheme


class NumberingSchemeSerializer(serializers.Serializer):
    """GET / PATCH response: the effective scheme + the prefix that would brand it.

    `is_effective` is False when the company carries no prefix — the custom mask is
    saved but the platform default is what actually mints (global-unique invariant).
    """

    pattern = serializers.CharField(read_only=True)
    padding = serializers.IntegerField(read_only=True)
    reset_period = serializers.CharField(read_only=True)
    start_value = serializers.IntegerField(read_only=True)
    prefix = serializers.CharField(read_only=True)
    is_effective = serializers.BooleanField(read_only=True)
    # Editable {type}-token label per doc kind (KP/CT/INV/ACT/DOC → shown text).
    type_labels = serializers.DictField(child=serializers.CharField(), read_only=True)


class NumberingSchemeWriteSerializer(serializers.Serializer):
    """PATCH body — shape/type validation only; the mask semantics ({seq} present,
    non-empty) and non-empty type labels are enforced by the model's full_clean inside
    `set_company_scheme`."""

    pattern = serializers.CharField(max_length=128, required=False)
    padding = serializers.IntegerField(min_value=1, max_value=20, required=False)
    reset_period = serializers.ChoiceField(choices=DocumentNumberingScheme.RESET_PERIOD_CHOICES, required=False)
    start_value = serializers.IntegerField(min_value=0, required=False)
    type_labels = serializers.DictField(child=serializers.CharField(max_length=32), required=False)


class NumberingPreviewRequestSerializer(serializers.Serializer):
    """POST preview body — a full DRAFT scheme to render examples for (dry-run).

    `prefix` is the editor's DRAFT brand prefix (optional): when sent, the `{prefix}` token
    renders from it so the example reflects an unsaved prefix live. Omitted → the persisted
    company prefix is used.
    """

    pattern = serializers.CharField(max_length=128)
    padding = serializers.IntegerField(min_value=1, max_value=20)
    reset_period = serializers.ChoiceField(choices=DocumentNumberingScheme.RESET_PERIOD_CHOICES)
    start_value = serializers.IntegerField(min_value=0)
    prefix = serializers.CharField(max_length=16, required=False, allow_blank=True)
    type_labels = serializers.DictField(child=serializers.CharField(max_length=32), required=False)


class NumberingPreviewItemSerializer(serializers.Serializer):
    """One rendered example number for a document kind (КП / CT / INV)."""

    type_code = serializers.CharField()
    label = serializers.CharField()
    number = serializers.CharField()


class NumberingPreviewResponseSerializer(serializers.Serializer):
    results = NumberingPreviewItemSerializer(many=True)
