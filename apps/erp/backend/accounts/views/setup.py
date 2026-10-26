"""Мастер первого запуска ERP (FIX-65): статус и создание своей компании.

GET  /api/v1/setup/status/   — любой вошедший: нужна ли первоначальная настройка и может ли её сделать он;
POST /api/v1/setup/company/  — только суперпользователь и только пока своей компании нет.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import permissions, serializers, status, views
from rest_framework.response import Response

from accounts.serializers import OwnCompanySetupSerializer
from accounts.services.own_company_setup import create_own_company, is_setup_required, own_company_id_or_none
from core.permissions import ADMIN_ONLY, IsPlatformAdmin, RoleGatedViewMixin


@extend_schema(
    summary="Статус первоначальной настройки ERP",
    responses={
        200: inline_serializer(
            "SetupStatus",
            fields={
                "setup_required": serializers.BooleanField(),
                "can_setup": serializers.BooleanField(),
                "own_company_id": serializers.IntegerField(
                    allow_null=True,
                    help_text="Id своей компании (core.tenant, с учётом OWN_COMPANY_ID); null — её нет.",
                ),
            },
        )
    },
    tags=["Setup"],
)
class SetupStatusView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        required = is_setup_required()
        return Response(
            {
                "setup_required": required,
                "can_setup": bool(required and request.user.is_superuser),
                # Платформа (BFF, W13-A3) берёт отсюда id своей компании: администратор работает без членства.
                "own_company_id": own_company_id_or_none(),
            }
        )


@extend_schema(
    summary="Создать свою компанию (мастер первого запуска)",
    description=(
        "Только суперпользователь и только пока своей компании нет. Создаёт компанию с типом продавца, "
        "делает текущего пользователя её владельцем. Ошибки полей — 422; повтор — 409 `OWN_COMPANY_ALREADY_EXISTS`."
    ),
    request=OwnCompanySetupSerializer,
    responses={
        201: inline_serializer(
            "OwnCompanyCreated", fields={"id": serializers.IntegerField(), "name": serializers.CharField()}
        ),
        403: OpenApiResponse(description="PLATFORM_ADMIN_REQUIRED"),
        409: OpenApiResponse(description="OWN_COMPANY_ALREADY_EXISTS"),
        422: OpenApiResponse(description="Ошибки полей формы"),
    },
    tags=["Setup"],
)
class SetupCompanyView(RoleGatedViewMixin, views.APIView):
    # Создать свою компанию может только администратор (`is_superuser`); матрица ролей требует объявления.
    required_permissions = {"POST": ADMIN_ONLY}
    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        serializer = OwnCompanySetupSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        company, error = create_own_company(request.user, serializer.validated_data)
        if error:
            return Response({"detail": error}, status=status.HTTP_409_CONFLICT)
        return Response({"id": company.pk, "name": company.name}, status=status.HTTP_201_CREATED)
