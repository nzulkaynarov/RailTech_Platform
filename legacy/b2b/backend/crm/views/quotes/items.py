"""КП line-item (`QuoteItem`) ViewSet + the seller-owns-deal write guard.

Split out of the monolithic ``crm/views/quotes.py`` (ARCH refactor) — behaviour
unchanged. Seller writes (create/update/destroy/reassign/bulk) are gated to the КП's
routed seller; buyer edits fall through to the request-item services.
"""

from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsCompanyMemberOrPlatformAdmin
from crm import services as crm_services
from crm.models import QuoteItem
from crm.serializers import QuoteItemSerializer


def _assert_seller_owns_quote_deal(request, quote):
    """A seller may only WRITE to a quote whose deal is routed to them. `perform_create`
    takes the target `quote` from the request body and bypasses the scoped get_queryset +
    object permission, so without this a seller could POST items/charges onto a COMPETITOR's
    КП (review 2026-06-25, CRITICAL #1). Superuser bypasses; platform-admin is already
    refused upstream by _assert_seller (ADMIN_VIEWER_CANNOT_ACT)."""
    from rest_framework.exceptions import PermissionDenied

    from accounts.services.permissions import seller_can_access_deal

    user = request.user
    if getattr(user, "is_superuser", False):
        return
    if quote is None or not seller_can_access_deal(user, request, quote.deal_id):
        raise PermissionDenied("NO_ACCESS_TO_DEAL")


@extend_schema_view(
    list=extend_schema(
        summary="List quote items",
        description="Returns quote line items accessible to the current user.",
        tags=["CRM"],
    ),
    create=extend_schema(
        summary="Create quote item",
        description="Add a line item to a quote.",
        tags=["CRM"],
    ),
    retrieve=extend_schema(summary="Get quote item", tags=["CRM"]),
    update=extend_schema(summary="Update quote item", tags=["CRM"]),
    partial_update=extend_schema(summary="Partially update quote item", tags=["CRM"]),
    destroy=extend_schema(summary="Delete quote item", tags=["CRM"]),
)
class QuoteItemViewSet(viewsets.ModelViewSet):
    """CRUD for quote line items (products, quantities, pricing)."""

    serializer_class = QuoteItemSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    # The КП builder grid renders EVERY line of a quote and recomputes economics over
    # all of them; the global DRF PAGE_SIZE=20 silently truncated the grid to the first
    # 20 rows while totals still reflected the full set — data loss for the seller.
    # A quote is a bounded document (line items per КП), so returning the full list is safe.
    pagination_class = None
    filterset_fields = {
        "quote__deal_id": ["exact"],
        "product": ["isnull", "exact"],
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return QuoteItem.objects.none()
        user = self.request.user
        from accounts.services.permissions import seller_visible_deal_ids

        queryset = QuoteItem.objects.all().select_related(
            "product", "product__domain_type", "quote", "offer", "offer__supplier", "frozen_currency"
        )
        if getattr(user, "is_platform_admin", False):
            return queryset
        visible_deal_ids = seller_visible_deal_ids(user, self.request)
        if visible_deal_ids is not None:
            from accounts.models import CompanyMember
            from accounts.services.permissions import (
                SELLER_COMPANY_TYPES,
                seller_acting_company_ids,
            )

            # The seller sees items/charges on deals routed to them. Audit H1 (no cross-seller
            # leak): hide a quote ONLY when it was prepared by a COMPETING seller company. The
            # buyer's request lines and the seller's КП are the SAME quote in this model, and
            # that quote is created by the BUYER (or left unassigned) — so scoping by
            # prepared_by's *seller* company alone wrongly hid the seller's own КП and made
            # pricing un-saveable (404 on item PATCH → subtotal stuck at 0). Exclude only
            # quotes whose prepared_by belongs to another seller company.
            seller_ids = seller_acting_company_ids(user, self.request) or set()
            # Dual-membership edge: a user who belongs to BOTH the viewer's own seller
            # company AND a competing one would otherwise land in competing_preparer_ids
            # and hide their OWN company's legitimately-prepared КП from their own viewers.
            # Subtract members of the viewer's OWN seller companies so only PURELY-competing
            # preparers are excluded.
            own_member_ids = CompanyMember.objects.filter(is_active=True, company_id__in=seller_ids).values_list(
                "user_id", flat=True
            )
            competing_preparer_ids = (
                CompanyMember.objects.filter(is_active=True, company__types__code__in=SELLER_COMPANY_TYPES)
                .exclude(company_id__in=seller_ids)
                .exclude(user_id__in=own_member_ids)
                .values_list("user_id", flat=True)
            )
            return (
                queryset.filter(quote__deal_id__in=visible_deal_ids)
                .exclude(quote__prepared_by_id__in=competing_preparer_ids)
                .distinct()
            )
        # Buyer sees line items only on their own deals (read-only — see _assert_seller).
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return queryset.filter(quote__deal__company_id__in=user_company_ids)

    def _assert_seller(self):
        """Building/editing КП line items is a seller action. Raise 403 otherwise."""
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import (
            can_edit_quote_pricing,
            is_platform_admin_viewer,
        )

        user = self.request.user
        if is_platform_admin_viewer(user):
            raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
        if not (getattr(user, "is_superuser", False) or can_edit_quote_pricing(user)):
            raise PermissionDenied("ONLY_SELLER_CAN_BUILD_QUOTE")

    def _is_seller_write(self) -> bool:
        from accounts.services.permissions import is_seller

        user = self.request.user
        return bool(getattr(user, "is_superuser", False) or is_seller(user))

    def perform_create(self, serializer):
        # Manual item creation on a КП is a seller action. Buyers add request
        # rows through POST /crm/deals/{id}/add-request-item/ instead (it
        # get-or-creates the DRAFT quote and restricts fields to name + qty).
        self._assert_seller()
        _assert_seller_owns_quote_deal(self.request, serializer.validated_data.get("quote"))
        serializer.save()

    def update(self, request, *args, **kwargs):
        """Optimistic-concurrency gate for a single-line PATCH (волна 3).

        DRF routes partial_update → update(partial=True), so this covers PATCH. When a SELLER
        write carries a `version` (the row revision the frontend last read) and it no longer
        matches the DB, a colleague saved this line in between — applying our edit would silently
        clobber theirs, so reject with 409 QUOTE_ITEM_STALE (same code the bulk path emits per
        row). `version` is OPTIONAL: a PATCH without it keeps the pre-волна-3 last-write-wins
        behaviour, so buyer request edits and version-less seller writes are untouched.
        """
        if self._is_seller_write():
            client_version = request.data.get("version")
            if client_version is not None:
                try:
                    client_version = int(client_version)
                except (TypeError, ValueError):
                    client_version = None
                instance = self.get_object()
                if client_version is None or client_version != instance.version:
                    return Response({"detail": "QUOTE_ITEM_STALE"}, status=status.HTTP_409_CONFLICT)
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        if self._is_seller_write():
            self._assert_seller()
            # Bump the optimistic-concurrency counter on a successful seller save (волна 3), so the
            # next stale-version save from a colleague is rejected. `version` is read-only on the
            # serializer, so set it on the instance before save; the full model save persists it.
            serializer.instance.version = (serializer.instance.version or 0) + 1
            serializer.save()
            return
        # Buyer editing their own still-open request — name + quantity only,
        # never pricing. The service re-checks can_buy + the editable window.
        crm_services.buyer_update_request_item(
            self.request.user,
            serializer.instance,
            name=serializer.validated_data.get("imported_raw_name"),
            quantity=serializer.validated_data.get("quantity"),
            unit=serializer.validated_data.get("unit"),
            unit_code=serializer.validated_data.get("unit_code"),
            note=serializer.validated_data.get("note"),
            mpn=serializer.validated_data.get("mpn"),
            name_canonical=serializer.validated_data.get("name_canonical"),
        )
        serializer.instance.refresh_from_db()

    def perform_destroy(self, instance):
        if self._is_seller_write():
            self._assert_seller()
            instance.delete()
            return
        crm_services.buyer_remove_request_item(self.request.user, instance)

    @extend_schema(
        summary="Manually reassign product for a quote item",
        tags=["CRM"],
        request=inline_serializer(
            "ReassignProduct",
            fields={
                "product_id": drf_serializers.IntegerField(allow_null=True),
            },
        ),
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="reassign-product",
        permission_classes=[IsAuthenticated],
    )
    def reassign_product(self, request, pk=None):
        # P0-2: re-matching an item to a catalog product is a SELLER action (КП assembly), NOT
        # platform-admin-only — the dialog renders on the seller's own КП page. _assert_seller
        # gates "is a seller"; get_object scopes to the seller's own visible items (a buyer can't
        # reach another tenant's item, and a buyer hitting their own item is refused by _assert_seller).
        self._assert_seller()
        item = self.get_object()
        product_id = request.data.get("product_id")
        updated, err = crm_services.reassign_quote_item_product(
            item.id,
            request.user,
            product_id=int(product_id) if product_id else None,
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(QuoteItemSerializer(updated).data)

    @extend_schema(
        summary="Bulk-update КП line items in one transaction",
        description=(
            "Save many edited КП lines atomically (P0-4). ALL-OR-NOTHING: if any line is "
            "invalid, nothing is saved and per-row errors are returned; on success the cascade "
            "and totals are recalculated ONCE and the updated lines are returned. Same guards / "
            "field validation as the single-item PATCH. Seller action."
        ),
        request=inline_serializer(
            "BulkUpdateQuoteItemsRequest",
            fields={
                "quote": drf_serializers.IntegerField(),
                "items": drf_serializers.ListField(child=drf_serializers.DictField()),
            },
        ),
        responses={
            200: QuoteItemSerializer(many=True),
            400: OpenApiResponse(
                description="QUOTE_ITEMS_BULK_INVALID (with per-row `rows`) / QUOTE_ITEMS_BULK_EMPTY / "
                "QUOTE_ITEMS_BULK_TOO_LARGE / QUOTE_FROZEN"
            ),
            403: OpenApiResponse(description="ADMIN_VIEWER_CANNOT_ACT / ONLY_SELLER_CAN_BUILD_QUOTE"),
            404: OpenApiResponse(description="QUOTE_NOT_FOUND"),
        },
        tags=["CRM"],
    )
    @action(detail=False, methods=["post"], url_path="bulk-update", permission_classes=[IsAuthenticated])
    def bulk_update(self, request):
        """Thin wrapper (Rule 8) — all logic in crm.services.quotes.bulk_update_quote_items."""
        from crm.services.quotes import bulk_update_quote_items

        items, error, rows = bulk_update_quote_items(
            request.user, request.data.get("quote"), request.data.get("items"), request
        )
        if error == "QUOTE_ITEMS_BULK_INVALID":
            return Response({"detail": error, "rows": rows}, status=status.HTTP_400_BAD_REQUEST)
        if error:
            http_status = {
                "ADMIN_VIEWER_CANNOT_ACT": status.HTTP_403_FORBIDDEN,
                "ONLY_SELLER_CAN_BUILD_QUOTE": status.HTTP_403_FORBIDDEN,
                "QUOTE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            }.get(error, status.HTTP_400_BAD_REQUEST)
            return Response({"detail": error}, status=http_status)
        return Response(self.get_serializer(items, many=True).data)

    @extend_schema(
        summary="Bulk-create КП line items in one transaction",
        description=(
            "Insert many new КП lines atomically (Excel-paste). ALL-OR-NOTHING: if any row is "
            "invalid, nothing is saved and per-row errors are returned; on success the cascade "
            "and totals are recalculated ONCE and the created lines are returned (201). Same "
            "field validation as the single-item create; every row needs a non-empty "
            "imported_raw_name. Seller action."
        ),
        request=inline_serializer(
            "BulkCreateQuoteItemsRequest",
            fields={
                "quote": drf_serializers.IntegerField(),
                "items": drf_serializers.ListField(child=drf_serializers.DictField()),
            },
        ),
        responses={
            201: QuoteItemSerializer(many=True),
            400: OpenApiResponse(
                description="QUOTE_ITEMS_BULK_INVALID (with per-row `rows`) / QUOTE_ITEMS_BULK_EMPTY / "
                "QUOTE_ITEMS_BULK_TOO_LARGE / QUOTE_FROZEN"
            ),
            403: OpenApiResponse(description="ADMIN_VIEWER_CANNOT_ACT / ONLY_SELLER_CAN_BUILD_QUOTE"),
            404: OpenApiResponse(description="QUOTE_NOT_FOUND"),
        },
        tags=["CRM"],
    )
    @action(detail=False, methods=["post"], url_path="bulk-create", permission_classes=[IsAuthenticated])
    def bulk_create(self, request):
        """Thin wrapper (Rule 8) — all logic in crm.services.quotes.bulk_create_quote_items."""
        from crm.services.quotes import bulk_create_quote_items

        items, error, rows = bulk_create_quote_items(
            request.user, request.data.get("quote"), request.data.get("items"), request
        )
        if error == "QUOTE_ITEMS_BULK_INVALID":
            return Response({"detail": error, "rows": rows}, status=status.HTTP_400_BAD_REQUEST)
        if error:
            http_status = {
                "ADMIN_VIEWER_CANNOT_ACT": status.HTTP_403_FORBIDDEN,
                "ONLY_SELLER_CAN_BUILD_QUOTE": status.HTTP_403_FORBIDDEN,
                "QUOTE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            }.get(error, status.HTTP_400_BAD_REQUEST)
            return Response({"detail": error}, status=http_status)
        return Response(self.get_serializer(items, many=True).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Get top-N smart-match candidates for this item", tags=["CRM"])
    @action(detail=True, methods=["get"], url_path="match-candidates", permission_classes=[IsAuthenticated])
    def match_candidates(self, request, pk=None):
        from sourcing.services import smart_match_candidates

        self._assert_seller()
        item = self.get_object()
        raw = item.imported_raw_name or (item.product.name if item.product else "")
        domain_hint = item.product.domain_type.code if (item.product and item.product.domain_type) else None
        candidates = smart_match_candidates(raw, limit=5, domain_hint=domain_hint)
        return Response({"raw": raw, "candidates": candidates})
