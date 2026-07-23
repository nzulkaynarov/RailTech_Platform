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
    is_owned = serializers.SerializerMethodField()
    public_url = serializers.SerializerMethodField()
    # Flat letterhead slice (name/ИНН/лого/подвал/accent) so the registry sheet renders the FULL
    # branded document — header + body + footer — instead of the bare body (T1-a). Frozen snapshot
    # once issued, live company branding for a draft.
    brand = serializers.SerializerMethodField()
    # Read-only mirror of public_token_revoked so the SPA can swap «Копировать ссылку» for a
    # «Ссылка отозвана» badge (J-b). public_url itself null-s once revoked.
    public_link_revoked = serializers.BooleanField(source="public_token_revoked", read_only=True)

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
            "is_owned",
            "public_url",
            "public_link_revoked",
            "brand",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _owner_company_ids(self):
        request = self.context.get("request")
        cached = self.context.get("_owner_company_ids")
        if cached is not None:
            return cached
        ids = set()
        if request is not None and getattr(request.user, "is_authenticated", False):
            ids = set(request.user.memberships.filter(is_active=True).values_list("company_id", flat=True))
        self.context["_owner_company_ids"] = ids
        return ids

    def get_is_owned(self, obj) -> bool:
        """True when the requester's company owns this document — the registry shows a «Получен»
        (read-only) badge on documents that are NOT owned (II-2)."""
        return obj.company_id in self._owner_company_ids()

    def get_public_url(self, obj) -> str | None:
        """Public no-login link (present only for ISSUED documents that carry a minted token)."""
        from crm.services.generated_documents import public_document_url

        return public_document_url(obj)

    def get_brand(self, obj) -> dict:
        """Flat letterhead slice for the registry preview (T1-a): frozen brand snapshot once issued,
        live company branding for a draft."""
        from crm.services.generated_documents import brand_letterhead_for_document

        return brand_letterhead_for_document(obj)

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
