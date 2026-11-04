"""`/api/v1/catalog/supplier-access/{id}/` — доступ поставщика в кабинет для карточки поставщика Платформы (ADR-0022).

Чтение — любой сотрудник бэк-офиса, изменения — `supply.manage` (то право, которым правят поставщиков).
Поставщик — тот, кто есть в списке поставщиков экрана (`catalog.desk.suppliers.supplier_queryset`); своя компания не входит.
"""

from django.db import transaction
from drf_spectacular.utils import extend_schema
from parties.models import Company
from portal.desk import service
from portal.desk.serializers import (
    DeskSupplierAccess,
    DeskSupplierAccessContact,
    DeskSupplierAccessContactIn,
    DeskSupplierAccessContactPatch,
    DeskSupplierAccessInviteIn,
    DeskSupplierAccessRelationshipPatch,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from catalog.desk import suppliers
from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, REFUSED, DeskViewSet

SUPPLY_MANAGE = "supply.manage"


def _can_manage(user) -> bool:
    from accounts.services.permissions import is_seller, staff_has_permission

    return bool(user.is_superuser or (is_seller(user) and staff_has_permission(user, SUPPLY_MANAGE)))


def _refused(error: service.AccessError) -> Response:
    return Response({"detail": error.code}, status=error.status)


class SupplierAccessViewSet(DeskViewSet):
    required_permissions = {
        "add_contact": SUPPLY_MANAGE,
        "update_contact": SUPPLY_MANAGE,
        "update_relationship": SUPPLY_MANAGE,
        "invite": SUPPLY_MANAGE,
        "suspend": SUPPLY_MANAGE,
    }
    lookup_value_regex = r"\d+"
    queryset = Company.objects.none()
    serializer_class = DeskSupplierAccess

    def _supplier(self, pk) -> Company:
        company = suppliers.supplier_queryset({}).filter(pk=pk).first()
        if company is None:
            raise NotFound()
        return company

    @extend_schema(
        operation_id="catalog_supplier_access_retrieve",
        summary="Supplier cabinet access",
        description="Отношение `supplier` поставщика (статус, кто и когда пригласил) и контакты компании.",
        responses={200: DeskSupplierAccess, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    def retrieve(self, request, pk=None):
        return Response(service.access_state(self._supplier(pk), can_manage=_can_manage(request.user)))

    @extend_schema(
        operation_id="catalog_supplier_access_contact_create",
        summary="Add a supplier contact",
        description=(
            "Needs `supply.manage`. ФИО и e-mail обязательны (вход только по e-mail), телефон и язык писем "
            "(ru, uz, en) — по желанию. Такой адрес уже есть у контакта компании — 409 `CONTACT_EXISTS`."
        ),
        request=DeskSupplierAccessContactIn,
        responses={201: DeskSupplierAccessContact, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="contacts", url_name="contacts")
    def add_contact(self, request, pk=None):
        company = self._supplier(pk)
        body = DeskSupplierAccessContactIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                contact = service.create_contact(company, dict(body.validated_data), request.user)
        except service.AccessError as error:
            return _refused(error)
        return Response(service.contact_row(contact), status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="catalog_supplier_access_contact_update",
        summary="Edit a supplier contact",
        description="Needs `supply.manage`. Приходят только изменённые поля.",
        request=DeskSupplierAccessContactPatch,
        responses={200: DeskSupplierAccessContact, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["patch"], url_path=r"contacts/(?P<contact_id>[0-9]+)", url_name="contact")
    def update_contact(self, request, pk=None, contact_id=None):
        company = self._supplier(pk)
        body = DeskSupplierAccessContactPatch(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                contact = service.update_contact(company, int(contact_id), dict(body.validated_data), request.user)
        except service.AccessError as error:
            return _refused(error)
        return Response(service.contact_row(contact))

    @extend_schema(
        operation_id="catalog_supplier_access_relationship_update",
        summary="Change partner rights in the cabinet",
        description=(
            "Needs `supply.manage`. Включённые модули (`my_products`, `catalog_requests`) и вид партнёра; действует сразу, "
            "без перевхода. Модуль не из шаблона роли — 400 `MODULE_NOT_ALLOWED`; отношения ещё нет — 404."
        ),
        request=DeskSupplierAccessRelationshipPatch,
        responses={200: DeskSupplierAccess, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["patch"], url_path="relationship", url_name="relationship")
    def update_relationship(self, request, pk=None):
        company = self._supplier(pk)
        body = DeskSupplierAccessRelationshipPatch(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        try:
            return Response(service.update_relationship(company, dict(body.validated_data), request.user))
        except service.AccessError as error:
            return _refused(error)

    @extend_schema(
        operation_id="catalog_supplier_access_invite",
        summary="Invite a supplier contact to the cabinet",
        description=(
            "Needs `supply.manage`. Создаёт отношение «партнёр» (или возвращает приостановленное) и отправляет контакту "
            "письмо с кодом входа на его языке. Письмо не ушло — 400 `EMAIL_DELIVERY_FAILED`, отношение не меняется; "
            "адрес общий с контактом другой компании кабинета — 409 `CONTACT_EMAIL_AMBIGUOUS`."
        ),
        request=DeskSupplierAccessInviteIn,
        responses={200: DeskSupplierAccess, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="invite", url_name="invite")
    def invite(self, request, pk=None):
        company = self._supplier(pk)
        body = DeskSupplierAccessInviteIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            data = body.validated_data
            return Response(
                service.invite(
                    company, data["contact_id"], request.user, modules=data.get("modules"), kind=data.get("kind")
                )
            )
        except service.AccessError as error:
            return _refused(error)

    @extend_schema(
        operation_id="catalog_supplier_access_suspend",
        summary="Suspend supplier cabinet access",
        description="Needs `supply.manage`. Вход закрыт, живые сессии партнёра гаснут на следующем запросе. Вернуть — «Пригласить».",
        request=None,
        responses={200: DeskSupplierAccess, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="suspend", url_name="suspend")
    def suspend(self, request, pk=None):
        company = self._supplier(pk)
        try:
            return Response(service.suspend(company, request.user))
        except service.AccessError as error:
            return _refused(error)
