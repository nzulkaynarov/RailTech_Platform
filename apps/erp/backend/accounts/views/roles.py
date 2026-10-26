"""Company roles API (Role+Permission-set) — thin wrappers over accounts.services.roles."""

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import services
from accounts.constants import PERMISSION_GROUPS
from accounts.serializers import CompanyRoleSerializer
from core.permissions import RoleGatedViewMixin

# Service error code → HTTP status.
_ERROR_STATUS = {
    "ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES": status.HTTP_403_FORBIDDEN,
    "SYSTEM_ROLE_IMMUTABLE": status.HTTP_403_FORBIDDEN,
    "ROLE_HAS_MEMBERS_REASSIGN_FIRST": status.HTTP_409_CONFLICT,
    "CANNOT_DROP_OWN_TEAM_MANAGE": status.HTTP_409_CONFLICT,
    "ROLE_COMPANY_MISMATCH": status.HTTP_403_FORBIDDEN,
    "MEMBER_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "ROLE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "ROLE_MANAGED_BY_CRM": status.HTTP_403_FORBIDDEN,
}


def _err(code):
    return Response({"detail": code}, status=_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST))


_GROUP_LABELS = {
    "deals": {"ru": "Запросы и сделки", "en": "Requests & deals"},
    "quotes": {"ru": "КП", "en": "Quotes"},
    "contracts": {"ru": "Договоры", "en": "Contracts"},
    "catalog": {"ru": "Каталог", "en": "Catalog"},
    "supply": {"ru": "Снабжение", "en": "Supply"},
    "fulfillment": {"ru": "Исполнение и логистика", "en": "Fulfillment & logistics"},
    "finance": {"ru": "Финансы", "en": "Finance"},
    "settings": {"ru": "Настройки и команда", "en": "Settings & team"},
    "data": {"ru": "Данные", "en": "Data"},
}
# English labels for the permission checkboxes (the .label on Permission is RU). The SPA
# localizes via i18n keys by code, but the catalog ships both so non-i18n clients render correctly.
_PERM_LABELS_EN = {
    "deal.manage": "Handle requests & deals",
    "deal.assign": "Assign the owner",
    "quote.build": "Build quotes",
    "quote.edit_pricing": "Edit prices, discounts & cost lines",
    "quote.view_cost_margin": "See cost & margin",
    "quote.send": "Send quotes to client",
    "quote.review": "Review quotes",
    "contract.manage": "Prepare contracts",
    "contract.sign": "Sign contracts for the company",
    "catalog.manage": "Maintain the catalog",
    "catalog.publish": "Publish items",
    "supply.manage": "Maintain suppliers & their offers",
    "fulfillment.manage": "Handle shipments & delivery notes",
    "fulfillment.act": "Issue acceptance acts",
    "finance.invoice": "Issue customer invoices",
    "finance.payment": "Record payments",
    "settings.edit": "Edit company details, templates & numbering",
    "settings.charge_templates": "Maintain quote cost-line templates",
    "team.manage": "Manage team & roles",
    "data.export": "Export data",
}


@extend_schema_view(
    list=extend_schema(
        summary="List company roles (assignable ones by default)",
        description=(
            "Роли, которые ведёт провижининг из CRM («CRM Sync: …», `managed_by_crm`), по умолчанию не отдаются — "
            "их нельзя назначить в «Команде». `include_managed=true` отдаёт их для чтения."
        ),
        parameters=[OpenApiParameter("include_managed", bool, required=False)],
        tags=["Accounts"],
    )
)
class CompanyRoleViewSet(RoleGatedViewMixin, viewsets.ModelViewSet):
    """Роли бэк-офиса своей компании (M1-ERP-05): системные шаблоны + свои; запись — `team.manage`."""

    required_permissions = {
        "create": "team.manage",
        "update": "team.manage",
        "partial_update": "team.manage",
        "destroy": "team.manage",
        "assign": "team.manage",
    }

    serializer_class = CompanyRoleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            from accounts.models import CompanyRole

            return CompanyRole.objects.none()
        # Список по умолчанию без ролей, которые ведёт CRM (их не назначают в «Команде»); `?include_managed=true`
        # отдаёт их для чтения. Карточка/правка/удаление достают любую роль — сервис ответит ROLE_MANAGED_BY_CRM.
        include_managed = self.action != "list" or self.request.query_params.get("include_managed") == "true"
        return services.list_roles_for_user(self.request.user, include_managed=include_managed)

    def create(self, request, *args, **kwargs):
        from core.tenant import own_company_id

        role, err = services.create_company_role(
            request.user, own_company_id(), request.data.get("name"), request.data.get("permissions", [])
        )
        if err:
            return _err(err)
        return Response(CompanyRoleSerializer(role).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        role, err = services.update_company_role(
            request.user, self.get_object(), request.data.get("name"), request.data.get("permissions", [])
        )
        if err:
            return _err(err)
        return Response(CompanyRoleSerializer(role).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        err = services.delete_company_role(request.user, self.get_object())
        if err:
            return _err(err)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Set a member's back-office roles (replaces the whole set; permissions are the union)",
        request=inline_serializer(
            "AssignCompanyRoles",
            fields={
                "member_id": serializers.IntegerField(),
                "role_ids": serializers.ListField(child=serializers.IntegerField()),
            },
        ),
        responses={
            200: inline_serializer(
                "AssignedCompanyRoles",
                fields={
                    "member_id": serializers.IntegerField(),
                    "role_ids": serializers.ListField(child=serializers.IntegerField()),
                },
            )
        },
        tags=["Accounts"],
    )
    @action(detail=False, methods=["post"], url_path="assign")
    def assign(self, request):
        member, err = services.set_member_roles(
            request.user, request.data.get("member_id"), request.data.get("role_ids")
        )
        if err:
            return _err(err)
        role_ids = sorted(member.company_roles.values_list("id", flat=True))
        return Response({"member_id": member.id, "role_ids": role_ids})


class PermissionCatalogView(APIView):
    """The permission checkbox catalog for the role editor (grouped, bilingual labels)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Company permission catalog",
        responses={
            200: inline_serializer(
                "CompanyPermissionCatalog",
                fields={"groups": serializers.ListField(child=serializers.DictField())},
            )
        },
        tags=["Accounts"],
    )
    def get(self, request):
        groups = []
        for key, perms in PERMISSION_GROUPS.items():
            groups.append(
                {
                    "key": key,
                    "label": _GROUP_LABELS.get(key, {}).get("ru", key),
                    "label_en": _GROUP_LABELS.get(key, {}).get("en", key),
                    "permissions": [
                        {"code": p.value, "label": p.label, "label_en": _PERM_LABELS_EN.get(p.value, p.label)}
                        for p in perms
                    ],
                }
            )
        return Response({"groups": groups})
