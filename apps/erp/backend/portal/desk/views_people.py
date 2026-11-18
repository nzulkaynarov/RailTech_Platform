"""`/api/v1/parties/people/` — люди контрагентов для «Органайзер · Люди» Платформы (FR-11, пункт 0.11 плана 2026-11-12).

Контакты клиентов своей компании (книга продавца, `accounts.services.clients.seller_clients`; сюда же проецируются
контакты клиентов CRM) и партнёров (поставщики и изготовители из списка поставщиков, компании с отношением «партнёр»).
Только чтение, любой сотрудник бэк-офиса; своя компания не входит. Компания и клиент, и поставщик — вид `client`.
Список — имя, компания, должность (их видят все, NAVIGATION «Люди»); телефон и почта — по одному человеку
(`retrieve`): Платформа открывает их по нажатию и пишет показ в журнал. Массовой выгрузки контактов нет.
"""

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from parties.models import Company, Contact
from parties.models.relationships import RelationshipRole
from parties.people import contact_names
from portal.desk import service_counterparty as counterparty
from portal.desk.serializers import (
    DeskCounterparty,
    DeskCounterpartyRoleIn,
    DeskOrganizationIn,
    DeskOrganizationPage,
    DeskPeoplePage,
    DeskPersonContacts,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from accounts.services.clients import seller_clients
from catalog.desk import suppliers
from catalog.desk.items import ItemError
from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, REFUSED, DeskViewSet, refuse
from core.permissions import SELF_SERVICE

KINDS = ("client", "partner")


def counterparty_ids(user) -> tuple[set, set]:
    """Клиенты своей компании и не клиенты — партнёры и организации-адресаты (компания и клиент, и поставщик — клиент)."""
    client_ids = set(seller_clients(user).values_list("pk", flat=True))
    partner_ids = set(suppliers.supplier_queryset({}).values_list("pk", flat=True)) | set(
        Company.objects.filter(
            Q(relationships__role=RelationshipRole.PARTNER) | Q(types__code="ORGANIZATION")
        ).values_list("pk", flat=True)
    )
    return client_ids, partner_ids - client_ids


def people_queryset(user, kind: str | None, q: str):
    client_ids, partner_ids = counterparty_ids(user)
    wanted = {"client": client_ids, "partner": partner_ids}.get(kind or "", client_ids | partner_ids)
    queryset = Contact.objects.select_related("company").filter(company_id__in=wanted)
    if q:
        queryset = queryset.filter(Q(name__icontains=q) | Q(company__name__icontains=q) | Q(position__icontains=q))
    return queryset.order_by("name", "pk"), client_ids


def person_row(contact: Contact, client_ids: set) -> dict:
    return {
        "id": contact.pk,
        "name": contact.name,
        "position": contact.position or None,
        "has_email": bool(contact.email),
        "has_phone": bool(contact.phone),
        "is_primary": contact.is_primary,
        "company": {"id": contact.company_id, "name": contact.company.name},
        "kind": "client" if contact.company_id in client_ids else "partner",
    }


class PeopleDeskViewSet(DeskViewSet):
    lookup_value_regex = r"\d+"
    queryset = Contact.objects.none()
    serializer_class = DeskPeoplePage

    @extend_schema(
        operation_id="parties_people_list",
        summary="List counterparty people",
        description=(
            "Контакты клиентов своей компании и партнёров (поставщики, изготовители, отношение «партнёр») для списка "
            "«Люди» Платформы. Компания и клиент, и поставщик — `client`. Своя компания не входит."
        ),
        parameters=[
            OpenApiParameter("kind", str, required=False, enum=list(KINDS), description="client | partner"),
            OpenApiParameter("q", str, required=False, description="Поиск по имени, компании, должности"),
            OpenApiParameter("page", int, required=False),
            OpenApiParameter("page_size", int, required=False),
        ],
        responses={200: DeskPeoplePage},
        tags=["Parties"],
    )
    def list(self, request):
        kind = request.query_params.get("kind")
        if kind not in KINDS:
            kind = None
        q = (request.query_params.get("q") or "").strip()[:100]
        queryset, client_ids = people_queryset(request.user, kind, q)
        return self.page_of(queryset, lambda rows: [person_row(row, client_ids) for row in rows])

    @extend_schema(
        operation_id="parties_people_contacts",
        summary="Phone and e-mail of a counterparty person",
        description="Телефон и почта одного человека из списка «Люди» — в тех же границах, что и список.",
        responses={200: DeskPersonContacts, 404: NOT_FOUND},
        tags=["Parties"],
    )
    def retrieve(self, request, pk=None):
        queryset, _ = people_queryset(request.user, None, "")
        contact = queryset.filter(pk=pk).first()
        if contact is None:
            raise NotFound()
        return Response(
            {"id": contact.pk, "name": contact.name, "phone": contact.phone or None, "email": contact.email or None}
        )


def organization_row(company: Company, client_ids: set, names: dict) -> dict:
    return {
        "id": company.pk,
        "name": company.name,
        "inn": company.inn or None,
        "email": company.email or None,
        "contact_person": names.get(company.pk) or None,
        "kind": "client" if company.pk in client_ids else "partner",
    }


def _organization_rows(rows, client_ids: set) -> list:
    names = contact_names(rows)
    return [organization_row(r, client_ids, names) for r in rows]


class OrganizationsDeskViewSet(DeskViewSet):
    """`/api/v1/parties/organizations/` — адресат письма из контрагентов (пункт «Ш» плана 2026-11-12).

    Организации в тех же границах, что и «Люди»: клиенты своей компании и партнёры, своя компания не входит. Название,
    ИНН, общая почта и контактное лицо организации — реквизиты для письма, не личные контакты человека, поэтому
    отдаются списком (почта и телефон людей — по-прежнему по одному, с записью в журнал).
    """

    queryset = Company.objects.none()
    serializer_class = DeskOrganizationPage

    @extend_schema(
        operation_id="parties_organizations_list",
        summary="Search counterparty organizations",
        description=(
            "Клиенты своей компании и партнёры для поля «Организация» письма: поиск по названию и ИНН, "
            "в ответе ИНН, общая почта и контактное лицо."
        ),
        parameters=[
            OpenApiParameter("q", str, required=False, description="Поиск по названию и ИНН"),
            OpenApiParameter("page", int, required=False),
            OpenApiParameter("page_size", int, required=False),
        ],
        responses={200: DeskOrganizationPage},
        tags=["Parties"],
    )
    def list(self, request):
        client_ids, partner_ids = counterparty_ids(request.user)
        queryset = Company.objects.filter(pk__in=client_ids | partner_ids)
        q = (request.query_params.get("q") or "").strip()[:100]
        if q:
            queryset = queryset.filter(Q(name__icontains=q) | Q(inn__icontains=q))
        return self.page_of(queryset.order_by("name", "pk"), lambda rows: _organization_rows(rows, client_ids))

    # --- карточка контрагента: одна компания во всех ролях (ADR-0028, СУЩ-2.5) ---------------------

    lookup_value_regex = r"\d+"
    # «Организацию» заводит любой сотрудник бэк-офиса — прямо из письма (ADR-0028 п. 5)
    required_permissions = {"roles": "supply.manage", "create": SELF_SERVICE}

    def _company(self, request, pk) -> tuple[Company, set]:
        client_ids, partner_ids = counterparty_ids(request.user)
        company = Company.objects.filter(pk=pk, pk__in=client_ids | partner_ids).first()
        if company is None:
            raise NotFound()
        return company, client_ids

    @extend_schema(
        operation_id="parties_organizations_create",
        summary="Create an addressee organization",
        description=(
            "Организация-адресат из письма (ADR-0028 п. 5, СУЩ-2.6): название, ИНН или рег. номер, страна, адрес; роль "
            "«Организация», без сделок. Такая компания уже есть (ИНН, пара «страна — рег. номер», без ИНН — название) — "
            "409 `COMPANY_EXISTS`, её выбирают из списка. Ответ — карточка контрагента."
        ),
        request=DeskOrganizationIn,
        responses={201: DeskCounterparty, 400: REFUSED, 409: REFUSED},
        tags=["Parties"],
    )
    def create(self, request):
        body = DeskOrganizationIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            company = counterparty.create_organization(body.validated_data, actor=request.user)
        except ItemError as error:
            return refuse(error)
        client_ids, _ = counterparty_ids(request.user)
        return Response(counterparty.card(company, client_ids, request.user), status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="parties_organizations_retrieve",
        summary="Counterparty card",
        description=(
            "Одна компания во всех ролях: роли-отметки, люди (без телефонов и почты), действующие банковские счета "
            "(номер полностью — держателю `finance.view` или `finance.payment`), бренды, которые она выпускает, и "
            "клиент CRM, если компания с ним связана. Те же границы, что у списка."
        ),
        responses={200: DeskCounterparty, 404: NOT_FOUND},
        tags=["Parties"],
    )
    def retrieve(self, request, pk=None):
        company, client_ids = self._company(request, pk)
        return Response(counterparty.card(company, client_ids, request.user))

    @extend_schema(
        operation_id="parties_organizations_by_crm_client",
        summary="Counterparty card by the CRM client id",
        description="Карточка компании, связанной с клиентом CRM; клиент ещё не передан в ERP — 404.",
        responses={200: DeskCounterparty, 404: NOT_FOUND},
        tags=["Parties"],
    )
    def by_crm_client(self, request, crm_client_id=None):
        # Свой адрес `parties/crm-clients/{id}/organization/` (core/urls.py): под `organizations/` он был бы
        # неотличим от `organizations/{id}/roles/`.
        from integration.models import CrmClientMapping

        company_id = (
            CrmClientMapping.objects.filter(crm_client_id=crm_client_id).values_list("company_id", flat=True).first()
        )
        company, client_ids = self._company(request, company_id)
        return Response(counterparty.card(company, client_ids, request.user))

    @extend_schema(
        operation_id="parties_organizations_roles",
        summary="Mark or unmark a counterparty role",
        description=(
            "Роль «поставщик» или «изготовитель» — отметкой, новая карточка не нужна (право `supply.manage`). Снять "
            "роль с предложениями или брендами нельзя — 409 `ROLE_IN_USE`; «клиент» и «партнёр с кабинетом» "
            "отметкой не меняются — 400 `ROLE_NOT_EDITABLE`."
        ),
        request=DeskCounterpartyRoleIn,
        responses={200: DeskCounterparty, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Parties"],
    )
    @action(detail=True, methods=["post"])
    def roles(self, request, pk=None):
        company, client_ids = self._company(request, pk)
        body = DeskCounterpartyRoleIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            counterparty.set_role(company, body.validated_data["role"], body.validated_data["on"], actor=request.user)
        except ItemError as error:
            return refuse(error)
        # снятая роль может вывести компанию из списка контрагентов — карточка отдаётся по прежним границам
        return Response(counterparty.card(company, client_ids, request.user))
