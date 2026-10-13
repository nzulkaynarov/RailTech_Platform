from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated


@extend_schema_view(
    list=extend_schema(
        summary="List sourcing requests",
        description=("Returns deals in SOURCING stage. " "B2B filtered: users see only their company's deals."),
        tags=["Sourcing"],
    ),
    retrieve=extend_schema(
        summary="Get sourcing request details",
        description="Returns details of a specific sourcing request (deal in SOURCING stage).",
        tags=["Sourcing"],
    ),
)
class AttachmentViewSet(viewsets.ModelViewSet):
    """
    Uploads/lists/deletes private attachments tied to exactly one parent
    (deal, message, quote, company, or product).

    - list: filter by deal/message/quote/company/product query params.
    - create: requires ONE of deal/message/quote/company/product, plus `file`.
    - destroy: only uploader or platform admin.

    Access to the attached entity is checked via the deal's company membership
    (or the product's manufacturer, or the company directly).
    """

    from .models import Attachment as _AttachmentModel
    from .serializers import AttachmentSerializer

    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        # Stream the file through this authenticated endpoint (get_object enforces
        # tenant scope) — the raw .url 404s on prod (local storage, no MinIO).
        from core.file_streaming import stream_file_field

        return stream_file_field(self.get_object().file, content_type="application/octet-stream")

    def get_queryset(self):
        from crm.models import Deal

        from .models import Attachment

        if getattr(self, "swagger_fake_view", False):
            return Attachment.objects.none()
        user = self.request.user
        qs = Attachment.objects.select_related(
            "deal__company",
            "message__deal__company",
            "quote__deal__company",
            "company",
            "product__owner_company",
        ).order_by("-uploaded_at")

        params = self.request.query_params
        if params.get("deal"):
            qs = qs.filter(deal_id=params["deal"])
        if params.get("message"):
            qs = qs.filter(message_id=params["message"])
        if params.get("quote"):
            qs = qs.filter(quote_id=params["quote"])
        if params.get("company"):
            qs = qs.filter(company_id=params["company"])
        if params.get("product"):
            qs = qs.filter(product_id=params["product"])

        if user.is_superuser:
            return qs

        user_company_ids = user.memberships.filter(is_active=True).values("company_id")

        # Subquery: avoid loading all deal IDs into memory
        from django.db.models import Q

        # A routed seller can reach their routed deals' attachments (the buyer's заявка
        # source-of-truth file) — review 2026-06-25 #5.
        from accounts.services.permissions import seller_visible_deal_ids

        seller_deal_ids = seller_visible_deal_ids(user, self.request) or set()
        accessible_deals = Deal.objects.filter(
            Q(company_id__in=user_company_ids)
            | Q(manager_id=user.id)
            | Q(client_id=user.id)
            | Q(id__in=seller_deal_ids),
        ).values("id")

        return qs.filter(
            Q(deal_id__in=accessible_deals)
            | Q(message__deal_id__in=accessible_deals)
            | Q(quote__deal_id__in=accessible_deals)
            | Q(company_id__in=user_company_ids)
            | Q(product__owner_company_id__in=user_company_ids),
        )

    def _assert_parent_access(self, validated):
        """Before create, verify user can attach to the chosen parent."""
        from rest_framework.exceptions import PermissionDenied

        user = self.request.user
        if user.is_superuser:
            return

        user_company_ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))

        deal = validated.get("deal")
        message = validated.get("message")
        quote = validated.get("quote")
        company = validated.get("company")
        product = validated.get("product")

        target_deal = deal or (message.deal if message else None) or (quote.deal if quote else None)
        if target_deal:
            if (
                target_deal.company_id in user_company_ids
                or target_deal.manager_id == user.id
                or target_deal.client_id == user.id
            ):
                return
            raise PermissionDenied("NO_ACCESS_TO_DEAL")
        if company:
            if company.id in user_company_ids:
                return
            raise PermissionDenied("NO_ACCESS_TO_COMPANY")
        if product:
            # Ownership moved from the deprecated `manufacturer` FK (always NULL now)
            # to `owner_company` — checking the old field denied every legitimate
            # owner (same class of bug as H1). Legacy fallback kept for pre-split rows.
            owner_id = product.owner_company_id or product.manufacturer_id
            if owner_id and owner_id in user_company_ids:
                return
            raise PermissionDenied("NO_ACCESS_TO_PRODUCT")
        raise PermissionDenied("NO_PARENT_PROVIDED")

    def perform_create(self, serializer):
        self._assert_parent_access(serializer.validated_data)
        file_obj = self.request.FILES.get("file")
        if not file_obj:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"file": "NO_FILE_PROVIDED"})
        # SEC-08: attachments are stored and later streamed for download — enforce the same
        # extension/content-type/size + magic-byte guard as other document uploads instead of
        # accepting arbitrary bytes (a .pdf-named executable was previously stored unchecked).
        from django.core.exceptions import ValidationError as DjangoValidationError
        from rest_framework.exceptions import ValidationError as DRFValidationError

        from core.validators import validate_document_upload

        try:
            validate_document_upload(file_obj)
        except DjangoValidationError as exc:
            raise DRFValidationError({"file": str(exc)})
        serializer.save(
            uploaded_by=self.request.user,
            original_filename=file_obj.name,
        )

    def perform_destroy(self, instance):
        user = self.request.user
        if not (user.is_superuser or instance.uploaded_by_id == user.id):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("ONLY_UPLOADER_OR_ADMIN_CAN_DELETE")
        if instance.file:
            instance.file.delete(save=False)
        instance.delete()
