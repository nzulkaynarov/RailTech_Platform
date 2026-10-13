"""``CompanyViewSet`` — CRUD + the buyer-facing supplier directory and CSV/XLSX export.

The KYC-verification / merge, document / logo / settings, and team-management
``@action`` endpoints live in sibling mixin modules (``company_kyc``,
``company_documents``, ``company_team``) so no single file exceeds the 500-line
limit. This is a pure code-move refactor — behaviour, ``url_path``/``url_name``,
permissions and the OpenAPI contract are unchanged. Mixins only ADD ``@action``
methods (they override nothing), so MRO does not affect behaviour.
"""

from django.db.models import ProtectedError
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import exceptions, filters, permissions
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts import services
from accounts.models import Company, CompanyMember
from accounts.serializers import CompanySerializer
from accounts.services.permissions import member_has_permission
from accounts.views.company_documents import CompanyDocumentsMixin
from accounts.views.company_kyc import CompanyKYCMixin
from accounts.views.company_team import CompanyTeamMixin
from core.permissions import IsPlatformAdmin


@extend_schema_view(
    list=extend_schema(
        summary="List companies",
        description="Returns all companies with KYC documents and members. Manager/Admin only.",
        tags=["Accounts"],
    ),
    create=extend_schema(
        summary="Create company",
        description="Register a new company. Manager/Admin only.",
        tags=["Accounts"],
    ),
    retrieve=extend_schema(
        summary="Get company details",
        description="Returns company details. Staff sees any company; members see only their own.",
        tags=["Accounts"],
    ),
    update=extend_schema(
        summary="Update company",
        description="Full update of company data (PUT). Manager/Admin only.",
        tags=["Accounts"],
    ),
    partial_update=extend_schema(
        summary="Partially update company",
        description="Partial update of company data (PATCH). Manager/Admin only.",
        tags=["Accounts"],
    ),
    destroy=extend_schema(
        summary="Delete company",
        description="Delete a company. Manager/Admin only.",
        tags=["Accounts"],
    ),
)
class CompanyViewSet(CompanyKYCMixin, CompanyDocumentsMixin, CompanyTeamMixin, viewsets.ModelViewSet):
    """
    CRUD operations for companies.

    Includes KYC verification, document upload, team management, and member invitations.
    """

    queryset = (
        Company.objects.select_related("verification_status", "country")
        .prefetch_related(
            "kyc_documents__doc_type",
            "types",
            "members",
        )
        .order_by("-created_at")
    )
    serializer_class = CompanySerializer
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    # Operator sub-capability per admin-only action (ADR-0004 G1). Member-facing actions
    # (see _MEMBER_ALLOWED_ACTIONS) bypass this via get_permissions; unmapped admin actions
    # fall back to the coarse platform-operator gate.
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        "verification_status__code": ["exact"],
        "types__code": ["exact"],
        # `?is_active=false` — вкладка «Архивные» (Odoo держит архив за фильтром, а не прячет).
        "is_active": ["exact"],
    }
    search_fields = ["name", "inn", "mfo", "contact_person", "email"]

    # Actions that a company member may perform on their own company
    # (logo upload, KYC document upload/delete, partial update of profile fields).
    # Actions a company MEMBER (not just a platform admin) may reach — the class is
    # otherwise IsPlatformAdmin. invite / update_member_capabilities enforce OWNER
    # inside the action itself, so IsAuthenticated here is correct (without this the
    # OWNER's own team-management is blocked with "platform administrators only").
    _MEMBER_ALLOWED_ACTIONS = {
        "retrieve",
        "update",
        "partial_update",
        "upload_document",
        "delete_document",
        "download_document",
        "upload_logo",
        "delete_logo",
        "document_profile",
        "document_profile_preview",
        "upload_document_profile_logo",
        "company_settings",
        "team",
        "invite",
        "update_member_capabilities",
        "set_member_role",
        "remove_member",
        "toggle_member_active",
    }

    def destroy(self, request, *args, **kwargs):
        """Удаление компании с историей запрещено — из оборота выводит АРХИВ.

        Дефолтный `ModelViewSet.destroy` сносил компанию каскадом: замер 24-08 — 204 и 2448
        удалённых строк, вместе с компанией исчезали её сделки, а участники оставались
        обезличенными аккаунтами без единого членства. Ни один эталон так не делает: Odoo
        отказывает и предлагает архив, Salesforce не даёт удалить даже пользователя, Stripe
        не удаляет финансовый факт вовсе.

        `ProtectedError` ловим ВТОРЫМ рубежом: гейт выше обязан не пропустить такие компании,
        но пятисотка не должна быть достижима даже при дыре в перечне держателей.
        """
        company = self.get_object()
        blocker = services.can_delete_company(company)
        if blocker:
            return Response({"detail": blocker}, status=status.HTTP_409_CONFLICT)
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            holders = sorted({obj._meta.verbose_name.title() for obj in exc.protected_objects})
            return Response(
                {"detail": "COMPANY_IN_USE" + (":" + ",".join(holders) if holders else "")},
                status=status.HTTP_409_CONFLICT,
            )

    @extend_schema(
        summary="Archive a company (Odoo Archive pattern)",
        description=(
            "Выводит компанию из оборота, сохраняя историю: она исчезает из подбора продавцов "
            "и справочников, но её сделки и документы остаются на месте. Причина обязательна "
            "и попадает в журнал."
        ),
        request=inline_serializer("ArchiveCompany", fields={"reason": drf_serializers.CharField()}),
        responses={200: CompanySerializer, 400: OpenApiResponse(description="REASON_REQUIRED")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        company, err = services.archive_company(self.get_object(), request.user, reason=request.data.get("reason", ""))
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(company).data)

    @extend_schema(
        summary="Return an archived company to circulation",
        responses={200: CompanySerializer, 400: OpenApiResponse(description="COMPANY_NOT_ARCHIVED")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="unarchive")
    def unarchive(self, request, pk=None):
        company, err = services.unarchive_company(self.get_object(), request.user)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(company).data)

    def get_permissions(self):
        # Member-facing actions (own-company self-service / OWNER team management) carry their
        # own in-action authz and must NOT hit the operator gate — BUT only for non-operators.
        # A platform OPERATOR calling these still goes through IsPlatformAdmin so a narrow role
        # (e.g. SUPPORT) cannot edit company data via update/partial_update (escalation fix).
        if self.action in self._MEMBER_ALLOWED_ACTIONS and not getattr(self.request.user, "is_superuser", False):
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    @extend_schema(
        summary="List verified suppliers (for RFQ invitations)",
        description=(
            "Minimal directory of verified SUPPLIER / MANUFACTURER companies a buyer "
            "can invite to an RFQ. Available to any authenticated member — returns only "
            "id, name and INN, NOT the full admin company record (no KYC internals)."
        ),
        responses={200: OpenApiResponse(description="List of {id, name, inn}")},
        tags=["Accounts"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="suppliers",
        permission_classes=[permissions.IsAuthenticated],
        pagination_class=None,
    )
    def suppliers(self, request):
        """Buyer-facing supplier directory for the open-RFQ invite flow.

        Deliberately narrow (id/name/inn) and capped to verified sellers, so the
        full company list — protected by IsPlatformAdmin — stays admin-only.

        Verified == the canonical KYC set (L2 + L3), NOT L2 alone: an L3_CONTRACTED seller
        is MORE verified than L2, and the old exact-L2 filter silently dropped exactly the
        contracted suppliers a buyer most wants to invite. This is also the same set the
        routing suggestion uses (sourcing.services), so a suggested seller is always a
        seller the buyer can actually see and un-check here.
        """
        verified_suppliers = Company.objects.verified_sellers().order_by("name").values("id", "name", "inn")
        return Response(list(verified_suppliers))

    def _assert_member_or_admin(self, company):
        user = self.request.user
        if user.is_superuser:
            return
        if not CompanyMember.objects.filter(
            user=user,
            company=company,
            is_active=True,
        ).exists():
            raise exceptions.PermissionDenied("ONLY_COMPANY_MEMBER_OR_ADMIN")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if not request.user.is_superuser:
            # Check if user is a member of this company
            membership = CompanyMember.objects.filter(user=request.user, company=instance).exists()
            if not membership:
                raise exceptions.PermissionDenied("You can only view your own company.")
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def _assert_owner_or_admin(self, company):
        """Editing the company profile is an OWNER action (or platform admin).
        Plain members may view but not change company data. The serializer's
        read_only_fields still protect KYC verdicts (verification_status /
        is_verified / trust_score) from any non-admin write."""
        user = self.request.user
        if user.is_superuser:
            return
        # ADR-0005 Phase E U3: gate on the CompanyRole permission, not the legacy OWNER
        # WorkspaceRole. member_has_permission's legacy fallback still grants a company_role-less
        # OWNER (the OWNER-role branch returns True for any perm), so an un-migrated OWNER keeps
        # access; a delegated admin holding settings.edit now passes too (the point of the engine).
        # A company_role-less NON-OWNER stays denied (settings.edit ∈ _ADMIN_PERMS → fallback False).
        # An OWNER deliberately reassigned to a restricted CompanyRole is governed by that role —
        # the intended U3 supersession, not an accidental lockout.
        if not member_has_permission(user, company.id, "settings.edit"):
            raise exceptions.PermissionDenied("ONLY_COMPANY_OWNER_OR_ADMIN")

    def update(self, request, *args, **kwargs):
        self._assert_owner_or_admin(self.get_object())
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._assert_owner_or_admin(self.get_object())
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        summary="Bulk verify KYC",
        description="Platform Admin: verify KYC for multiple companies in one request.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "integer"}},
                    "level": {"type": "string", "default": "L2_VERIFIED"},
                    "reason": {"type": "string"},
                },
                "required": ["ids"],
            }
        },
        responses={200: OpenApiResponse(description="approved count + skipped")},
        tags=["Accounts"],
    )
    @extend_schema(
        summary="Export companies",
        description="Export filtered companies list as CSV or XLSX (format=csv|xlsx).",
        tags=["Accounts"],
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        from core.exporters import export_queryset

        qs = self.filter_queryset(self.get_queryset())

        def _types(c):
            return ",".join(sorted(t.code for t in c.types.all()))

        return export_queryset(
            qs,
            request=request,
            filename="companies",
            columns=[
                ("id", "ID", lambda c: c.id),
                ("name", "Name", lambda c: c.name),
                ("inn", "INN", lambda c: c.inn or ""),
                ("verification", "KYC", lambda c: c.verification_status.code if c.verification_status_id else ""),
                ("types", "Types", _types),
                ("email", "Email", lambda c: c.email or ""),
                ("phone", "Phone", lambda c: c.phone or ""),
                ("contact_person", "Contact", lambda c: c.contact_person or ""),
                ("created_at", "Created", lambda c: c.created_at.isoformat() if c.created_at else ""),
            ],
        )
