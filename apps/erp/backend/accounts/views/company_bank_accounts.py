"""Банковские счета компании для ``CompanyViewSet`` (решение владельца 2026-11-11): список, добавить, изменить,
удалить. Только держатель `settings.edit` своей компании (как профиль документов)."""

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from parties.models import CompanyBankAccount
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts import services
from accounts.serializers import CompanyBankAccountSerializer
from accounts.services import bank_accounts

_BODY = inline_serializer(
    "CompanyBankAccountWrite",
    fields={
        "bank_country": serializers.CharField(
            required=False, allow_blank=True, help_text="Страна банка, ISO 3166-1 alpha-2; без неё при создании — UZ"
        ),
        "holder_name": serializers.CharField(required=False, allow_blank=True),
        "holder_name_latin": serializers.CharField(required=False, allow_blank=True),
        "bank_name": serializers.CharField(required=False, allow_blank=True),
        "bank_address": serializers.CharField(required=False, allow_blank=True),
        "mfo": serializers.CharField(required=False, allow_blank=True, help_text="Код банка в стране (МФО)"),
        "account": serializers.CharField(required=False),
        "currency": serializers.CharField(required=False, help_text="Код валюты справочника (UZS, USD, …)"),
        "swift": serializers.CharField(required=False, allow_blank=True),
        "intermediary_swift": serializers.CharField(required=False, allow_blank=True),
        "intermediary_account": serializers.CharField(required=False, allow_blank=True),
        "correspondent_bank": serializers.CharField(required=False, allow_blank=True),
        "is_default": serializers.BooleanField(required=False),
        "is_active": serializers.BooleanField(required=False),
        "order": serializers.IntegerField(required=False),
    },
)
_INVALID = OpenApiResponse(
    description=(
        "Ошибки полей в виде DRF: {поле: [причина]} — required, unknown, too_long, taken, inactive и проверки ADR-0029: "
        "uz_format, currency_mismatch, iban_invalid, iban_country, format, invalid, country_mismatch, latin_charset"
    )
)


def _invalid(errors):
    return Response({name: [reason] for name, reason in errors.items()}, status=status.HTTP_400_BAD_REQUEST)


class CompanyBankAccountsMixin:
    """``@action`` эндпоинты счетов компании."""

    @extend_schema(
        summary="Company bank accounts",
        description="GET — счета компании (основные первыми); POST — добавить счёт. Первый счёт валюты становится "
        "основным; назначение основного снимает флаг с прежнего счёта той же валюты.",
        request=_BODY,
        responses={200: CompanyBankAccountSerializer(many=True), 201: CompanyBankAccountSerializer, 400: _INVALID},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["get", "post"], url_path="bank-accounts")
    def bank_accounts(self, request, pk=None):
        company = self.get_object()
        if not services.is_company_owner(request.user, company):
            return Response({"detail": "NOT_COMPANY_OWNER"}, status=status.HTTP_403_FORBIDDEN)
        if request.method == "POST":
            row, errors = bank_accounts.save_account(company, dict(request.data))
            if errors:
                return _invalid(errors)
            return Response(CompanyBankAccountSerializer(row).data, status=status.HTTP_201_CREATED)
        rows = CompanyBankAccount.objects.filter(company=company).select_related("currency")
        return Response(CompanyBankAccountSerializer(rows, many=True).data)

    @extend_schema(
        summary="Company bank account",
        description="PATCH — изменить счёт; DELETE — удалить.",
        request=_BODY,
        responses={
            200: CompanyBankAccountSerializer,
            204: None,
            400: _INVALID,
            404: OpenApiResponse(description="Нет"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["patch", "delete"], url_path=r"bank-accounts/(?P<account_id>[0-9]+)")
    def bank_account(self, request, pk=None, account_id=None):
        company = self.get_object()
        if not services.is_company_owner(request.user, company):
            return Response({"detail": "NOT_COMPANY_OWNER"}, status=status.HTTP_403_FORBIDDEN)
        row = CompanyBankAccount.objects.filter(company=company, pk=account_id).select_related("currency").first()
        if row is None:
            return Response({"detail": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if request.method == "DELETE":
            row.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        updated, errors = bank_accounts.save_account(company, dict(request.data), row)
        if errors:
            return _invalid(errors)
        return Response(CompanyBankAccountSerializer(updated).data)
