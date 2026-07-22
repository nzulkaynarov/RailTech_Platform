"""«Документы 2.0» serializers — template library + generated documents.

Representation-focused: writes flow through crm.services (sanitisation, placeholder
derivation, numbering, status transitions), so these are thin read serializers plus
a couple of write fields the ViewSet hands to the services.
"""

from rest_framework import serializers

from crm.models import DocumentTemplate, GeneratedDocument


class DocumentTemplateSerializer(serializers.ModelSerializer):
    """Company template CRUD. `company`/`placeholders_used` are server-derived."""

    kind = serializers.SlugRelatedField(slug_field="code", read_only=True)
    kind_code = serializers.CharField(source="kind.code", read_only=True)
    kind_name = serializers.CharField(source="kind.name", read_only=True)
    is_owned = serializers.SerializerMethodField()

    class Meta:
        model = DocumentTemplate
        fields = [
            "id",
            "name",
            "kind",
            "kind_code",
            "kind_name",
            "body_html",
            "placeholders_used",
            "is_sample",
            "is_active",
            "is_owned",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["placeholders_used", "is_sample", "created_at", "updated_at"]

    def get_is_owned(self, obj) -> bool:
        """True when the requester's company owns this template (vs a platform sample)."""
        request = self.context.get("request")
        owner_company_id = self.context.get("owner_company_id")
        if owner_company_id is None and request is not None:
            from crm.services import resolve_owner_company_id

            owner_company_id = resolve_owner_company_id(request.user)
        return bool(obj.company_id and obj.company_id == owner_company_id)


class GeneratedDocumentSerializer(serializers.ModelSerializer):
    """A rendered document. Snapshot fields (`values`, `rendered_html`) are read-only
    here — DRAFT edits go through the dedicated update-values action."""

    status_code = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    template_name = serializers.CharField(source="template.name", read_only=True)
    deal_title = serializers.SerializerMethodField()
    contact_name = serializers.CharField(source="contact.name", read_only=True, default=None)
    created_by_name = serializers.SerializerMethodField()
    pdf_available = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedDocument
        fields = [
            "id",
            "number",
            "title",
            "status",
            "status_code",
            "status_name",
            "template",
            "template_name",
            "deal",
            "deal_title",
            "contact",
            "contact_name",
            "values",
            "rendered_html",
            "pdf_available",
            "issued_at",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_deal_title(self, obj) -> str | None:
        if obj.deal_id is None:
            return None
        return obj.deal.title or f"#{obj.deal_id}"

    def get_created_by_name(self, obj) -> str | None:
        if obj.created_by_id is None:
            return None
        return obj.created_by.get_full_name() or obj.created_by.email

    def get_pdf_available(self, obj) -> bool:
        return bool(obj.pdf_file)
