"""`/api/v1/parties/people/` — люди контрагентов для «Органайзер · Люди» Платформы (FR-11, пункт 0.11 плана 2026-11-12).

Контакты клиентов своей компании (книга продавца `accounts.services.clients.seller_clients`: тип CLIENT, связь с
клиентом CRM или сделка) и партнёров (поставщики и изготовители из списка поставщиков, компании с отношением «партнёр»).
Только чтение, любой сотрудник бэк-офиса; своя компания не входит. Компания и клиент, и поставщик — вид `client`.
Список — имя, компания, должность (их видят все, NAVIGATION «Люди»); телефон и почта — по одному человеку
(`retrieve`): Платформа открывает их по нажатию и пишет показ в журнал. Единственное исключение — почта людей одной
компании для поля выбора (`organizations/{id}/people/`, Q-ED6-1): она отдаётся списком, телефона в нём нет.
"""

from django.db.models import Case, IntegerField, Q, When
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from integration.models import CrmClientMapping
from parties import pictures
from parties.models import Company, Contact
from parties.models.contacts import active_contact_q
from parties.models.relationships import RelationshipRole, RelationshipStatus
from parties.people import contact_names
from portal.desk import service_counterparty as counterparty
from portal.desk.serializers import (
    DeskCounterparty,
    DeskCounterpartyLogos,
    DeskCounterpartyRequisitesIn,
    DeskCounterpartyRoleIn,
    DeskDoNotWorkIn,
    DeskOrganizationIn,
    DeskOrganizationPage,
    DeskOrganizationPeople,
    DeskPeoplePage,
    DeskPersonContacts,
    DeskPersonPhoto,
    DeskPictureIn,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import MultiPartParser
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
        "photo_version": pictures.version(contact.photo),
    }


#: Кто правит логотип и фото контакта: те же, кто правит реквизиты контрагента (новых прав нет)
PICTURE_EDITORS = ("deal.manage", "supply.manage")
PICTURE_RESPONSES = {200: {"type": "string", "format": "binary"}, 404: NOT_FOUND}


def picture_response(field, request) -> HttpResponse:
    """Картинка по запросу: 404, пока её нет или файла нет в хранилище; кэш браузера держит адрес с `?v=` (версия)."""
    if not field:
        raise NotFound()
    try:
        data = pictures.render(field, request.query_params.get("size", "row"))
    except (OSError, ValueError):
        pictures.logger.warning("picture %s is unreadable", field.name)
        raise NotFound() from None
    return HttpResponse(data, content_type="image/webp", headers={"Cache-Control": "private, max-age=300"})


def picture_upload(request):
    """Файл из формы или отказ 400 `FILE_REQUIRED`."""
    body = DeskPictureIn(data=request.data)
    body.is_valid(raise_exception=True)
    return body.validated_data["file"]


class PeopleDeskViewSet(DeskViewSet):
    lookup_value_regex = r"\d+"
    queryset = Contact.objects.none()
    serializer_class = DeskPeoplePage
    required_permissions = {"photo": PICTURE_EDITORS}

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

    @extend_schema(
        methods=["GET"],
        operation_id="parties_people_photo_get",
        summary="Photo of a counterparty person",
        description="Фото контакта: WebP 96 px (`size=full` — 256 px). Читает любой сотрудник в границах списка «Люди»; фото нет — 404.",
        parameters=[
            OpenApiParameter("size", str, required=False, enum=sorted(pictures.SIZES), description="row | full")
        ],
        responses=PICTURE_RESPONSES,
        tags=["Parties"],
    )
    @extend_schema(
        methods=["PUT"],
        operation_id="parties_people_photo_put",
        summary="Upload or replace the photo of a counterparty person",
        description=(
            "СУЩ-3. Квадратное фото (клиент уже обрезал по кругу), JPEG, PNG или WebP до 2 МБ; сервер перекодирует в WebP "
            "256×256. Право `deal.manage` или `supply.manage`. Не тот тип — 400 `FILE_TYPE_NOT_ALLOWED`, подпись не совпала — "
            "400 `FILE_CONTENT_MISMATCH`, больше 2 МБ — 400 `FILE_TOO_LARGE`. Ответ — `photo_version`."
        ),
        request={"multipart/form-data": DeskPictureIn},
        responses={200: DeskPersonPhoto, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Parties"],
    )
    @extend_schema(
        methods=["DELETE"],
        operation_id="parties_people_photo_delete",
        summary="Remove the photo of a counterparty person",
        description="Убирает фото и файл; повтор безопасен. Тот же доступ. Ответ — `photo_version: null`.",
        responses={200: DeskPersonPhoto, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Parties"],
    )
    @action(detail=True, methods=["get", "put", "delete"], url_path="photo", parser_classes=[MultiPartParser])
    def photo(self, request, pk=None):
        queryset, _ = people_queryset(request.user, None, "")
        contact = queryset.filter(pk=pk).first()
        if contact is None:
            raise NotFound()
        if request.method == "GET":
            return picture_response(contact.photo, request)
        if request.method == "DELETE":
            pictures.remove(contact, "photo")
        else:
            try:
                pictures.replace(contact, "photo", picture_upload(request))
            except ItemError as error:
                return refuse(error)
        return Response({"id": contact.pk, "photo_version": pictures.version(contact.photo)})


def organization_row(company: Company, client_ids: set, names: dict, roles: dict, crm_ids: dict) -> dict:
    return {
        "id": company.pk,
        "name": company.name,
        "inn": company.inn or None,
        "email": company.email or None,
        "contact_person": names.get(company.pk) or None,
        "kind": "client" if company.pk in client_ids else "partner",
        "roles": roles[company.pk],
        "country": company.country.name if company.country_id else None,
        "crm_client_id": crm_ids.get(company.pk),
        "logo_version": pictures.version(company.logo),
    }


def _organization_rows(rows, client_ids: set) -> list:
    rows = list(rows)
    names = contact_names(rows)
    roles = counterparty.roles_for(rows, client_ids)
    crm_ids = dict(
        CrmClientMapping.objects.filter(company__in=rows).order_by("-pk").values_list("company_id", "crm_client_id")
    )
    return [organization_row(r, client_ids, names, roles, crm_ids) for r in rows]


#: Роль-подсказка поля выбора: строки с этой ролью идут выше, остальные не скрываются
ROLE_FILTERS = ("client", "supplier", "manufacturer", "partner", "organization")
PICKER_LIMIT = 20


def _role_match(role: str, client_ids: set):
    """Условие «у компании есть роль» — те же отметки, что `service_counterparty.roles_of`."""
    if role == "client":
        return Q(pk__in=client_ids)
    if role == "supplier":
        return Q(types__code="SUPPLIER") | Q(supplier_offers__isnull=False)
    if role == "manufacturer":
        return Q(types__code="MANUFACTURER")
    if role == "partner":
        return Q(
            relationships__role=RelationshipRole.PARTNER,
            relationships__status__in=(RelationshipStatus.INVITED, RelationshipStatus.ACTIVE),
        )
    return Q(types__code="ORGANIZATION")


def _picker_order(queryset, q: str, role: str | None, client_ids: set):
    """Порядок поля выбора: точный ИНН, затем компании с нужной ролью, затем название."""
    keys = []
    if q:
        exact = Q(inn=q) | Q(stated_inn=q)
        queryset = queryset.annotate(inn_exact=Case(When(exact, then=0), default=1, output_field=IntegerField()))
        keys.append("inn_exact")
    if role:
        wanted = Company.objects.filter(_role_match(role, client_ids)).values("pk")
        queryset = queryset.annotate(
            role_rank=Case(When(pk__in=wanted, then=0), default=1, output_field=IntegerField())
        )
        keys.append("role_rank")
    return queryset.order_by(*keys, "name", "pk")


class OrganizationsDeskViewSet(DeskViewSet):
    """`/api/v1/parties/organizations/` — адресат письма из контрагентов (пункт «Ш» плана 2026-11-12).

    Организации в тех же границах, что и «Люди»: клиенты своей компании и партнёры, своя компания не входит. Название,
    ИНН, общая почта и контактное лицо организации — реквизиты для письма, не личные контакты человека, поэтому
    отдаются списком; почта людей одной компании — тоже списком, для поля выбора (Q-ED6-1), телефон людей — только
    по одному, с записью в журнал.
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
            OpenApiParameter("q", str, required=False, description="Поиск по названию и ИНН; точный ИНН — первым"),
            OpenApiParameter(
                "role",
                str,
                required=False,
                enum=list(ROLE_FILTERS),
                description="Роль-подсказка: компании с ней идут выше, остальные не скрываются",
            ),
            OpenApiParameter(
                "limit",
                int,
                required=False,
                description="Поле выбора: первые N строк (до 20) одним списком, без страниц",
            ),
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
            queryset = queryset.filter(Q(name__icontains=q) | Q(inn__icontains=q) | Q(stated_inn__icontains=q))
        role = request.query_params.get("role")
        role = role if role in ROLE_FILTERS else None
        queryset = _picker_order(queryset.select_related("country"), q, role, client_ids)
        limit = request.query_params.get("limit")
        if limit and limit.isdigit() and int(limit) > 0:
            rows = _organization_rows(queryset[: min(int(limit), PICKER_LIMIT)], client_ids)
            return Response({"count": len(rows), "next": None, "previous": None, "results": rows})
        return self.page_of(queryset, lambda rows: _organization_rows(rows, client_ids))

    # --- карточка контрагента: одна компания во всех ролях (ADR-0028, СУЩ-2.5) ---------------------

    lookup_value_regex = r"\d+"
    # «Организацию» заводит любой сотрудник бэк-офиса — прямо из письма (ADR-0028 п. 5)
    required_permissions = {
        "roles": "supply.manage",
        "create": SELF_SERVICE,
        # СУЩ-2.7: реквизиты контрагента правит менеджер или снабжение — их ведёт ERP
        "partial_update": ("deal.manage", "supply.manage"),
        # ЕД-5: логотип правит тот же, кто правит реквизиты
        "logo": PICTURE_EDITORS,
        # Х-8: «Не работать» ставит и снимает тот же, кто правит реквизиты контрагента
        "do_not_work": ("deal.manage", "supply.manage"),
    }

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
            "409 `COMPANY_EXISTS` с `existing_id` (поиск среди всех компаний) и `existing` — строкой выбора этой компании, "
            "даже если она без роли и в списке её нет. Роль — "
            "«организация» по умолчанию; «поставщик» и «изготовитель» — право `supply.manage`, иначе 403 "
            "`ROLE_PERMISSION_REQUIRED`. Ответ — карточка контрагента."
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
            response = refuse(error)
            twin_id = error.extra.get("existing_id")
            if error.code == "COMPANY_EXISTS" and twin_id:
                # the twin may sit outside the picker boundary (no role): its card is unreadable for the caller,
                # so the picker row travels in the refusal itself
                client_ids, _ = counterparty_ids(request.user)
                twin = Company.objects.select_related("country").filter(pk=twin_id).first()
                if twin is not None:
                    response.data["existing"] = _organization_rows([twin], client_ids)[0]
            return response
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
        operation_id="parties_organizations_partial_update",
        summary="Edit counterparty requisites",
        description=(
            "Название, ИНН, рег. номер, страна и юридический адрес контрагента (ADR-0028 п. 6, СУЩ-2.7): их ведёт ERP, "
            "CRM получает снимок `company.updated`. Право `deal.manage` или `supply.manage`. Пустое название — 400 "
            "`COMPANY_NAME_REQUIRED`; ИНН или пара «страна — рег. номер» другой компании — 409 `COMPANY_EXISTS`."
        ),
        request=DeskCounterpartyRequisitesIn,
        responses={200: DeskCounterparty, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Parties"],
    )
    def partial_update(self, request, pk=None):
        company, client_ids = self._company(request, pk)
        body = DeskCounterpartyRequisitesIn(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        try:
            counterparty.update_requisites(company, body.validated_data, actor=request.user)
        except ItemError as error:
            return refuse(error)
        return Response(counterparty.card(company, client_ids, request.user))

    @extend_schema(
        methods=["GET"],
        operation_id="parties_organizations_logo_get",
        summary="Counterparty logo",
        description="Логотип: WebP 96 px (`size=full` — 256 px). Читает любой сотрудник в границах списка контрагентов; логотипа нет — 404.",
        parameters=[
            OpenApiParameter("size", str, required=False, enum=sorted(pictures.SIZES), description="row | full")
        ],
        responses=PICTURE_RESPONSES,
        tags=["Parties"],
    )
    @extend_schema(
        methods=["PUT"],
        operation_id="parties_organizations_logo_put",
        summary="Upload or replace the counterparty logo",
        description=(
            "ЕД-5. Квадрат, обрезанный клиентом; JPEG, PNG или WebP до 2 МБ, сервер перекодирует в WebP 256×256. Право "
            "`deal.manage` или `supply.manage`. Отказы файла — 400 `FILE_TYPE_NOT_ALLOWED`, `FILE_CONTENT_MISMATCH`, "
            "`FILE_TOO_LARGE`. Ответ — карточка контрагента с новой `logo_version`."
        ),
        request={"multipart/form-data": DeskPictureIn},
        responses={200: DeskCounterparty, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Parties"],
    )
    @extend_schema(
        methods=["DELETE"],
        operation_id="parties_organizations_logo_delete",
        summary="Remove the counterparty logo",
        description="Убирает логотип и файл; повтор безопасен. Тот же доступ. Ответ — карточка контрагента.",
        responses={200: DeskCounterparty, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Parties"],
    )
    @action(detail=True, methods=["get", "put", "delete"], url_path="logo", parser_classes=[MultiPartParser])
    def logo(self, request, pk=None):
        if request.method == "GET":
            # своя компания не контрагент, но её логотип показывают «Компания» и бланки: читать его можно
            from core.tenant import own_company

            own = own_company()
            if own is not None and str(own.pk) == str(pk):
                return picture_response(own.logo, request)
        company, client_ids = self._company(request, pk)
        if request.method == "GET":
            return picture_response(company.logo, request)
        if request.method == "DELETE":
            pictures.remove(company, "logo")
        else:
            try:
                pictures.replace(company, "logo", picture_upload(request))
            except ItemError as error:
                return refuse(error)
        return Response(counterparty.card(company, client_ids, request.user))

    @extend_schema(
        operation_id="parties_organizations_logos",
        summary="Logo versions of several counterparties",
        description=(
            "Версии логотипов компаний `ids` (до 100, через запятую) в границах списка контрагентов: строки реестров, где "
            "компания приходит из CRM, получают адрес `…/logo/?v=` одним запросом. Чужие и неизвестные id в ответ не входят."
        ),
        parameters=[OpenApiParameter("ids", str, required=True, description="id компаний через запятую, до 100")],
        responses={200: DeskCounterpartyLogos},
        tags=["Parties"],
    )
    @action(detail=False, methods=["get"], url_path="logos")
    def logos(self, request):
        wanted = [int(x) for x in (request.query_params.get("ids") or "").split(",") if x.strip().isdigit()][:100]
        client_ids, partner_ids = counterparty_ids(request.user)
        rows = Company.objects.filter(pk__in=set(wanted) & (client_ids | partner_ids)).only("id", "logo")
        return Response({"results": {str(c.pk): pictures.version(c.logo) for c in rows}})

    @extend_schema(
        operation_id="parties_organizations_people",
        summary="People of a counterparty for a picker",
        description=(
            "Люди компании для поля выбора человека: имя, должность и почта (телефон — только по одному через "
            "`parties/people`). Те же границы, что у списка; главный контакт первым."
        ),
        responses={200: DeskOrganizationPeople, 404: NOT_FOUND},
        tags=["Parties"],
    )
    @action(detail=True, methods=["get"], url_path="people")
    def people(self, request, pk=None):
        company, _ = self._company(request, pk)
        contacts = company.contacts.filter(active_contact_q()).order_by("-is_primary", "name", "pk")
        return Response(
            {
                "results": [
                    {
                        "id": c.pk,
                        "name": c.name,
                        "position": c.position or None,
                        "email": c.email or None,
                        "is_primary": c.is_primary,
                        "photo_version": pictures.version(c.photo),
                    }
                    for c in contacts
                ]
            }
        )

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

    @extend_schema(
        methods=["POST"],
        operation_id="parties_organizations_do_not_work_set",
        summary="Mark a counterparty «do not work»",
        description=(
            "Х-8. Отметить «Не работать»: причина обязательна (400 `REASON_REQUIRED`), дата окончания по желанию (в прошлом — "
            "400 `UNTIL_PAST`); повторная отметка заменяет прежнюю. Право `deal.manage` или `supply.manage`. Новые КП, договор, "
            "заказ поставщику и заявка у такой компании отказываются 409 `COMPANY_DO_NOT_WORK` с причиной и тем, кто "
            "отметил; приглашения её контактов в кабинет не уходят; документы в работе не отменяются, кабинет читает как "
            "прежде. Действие пишется в журнал, CRM получает отметку в снимке `company.updated`. Ответ — карточка контрагента."
        ),
        request=DeskDoNotWorkIn,
        responses={200: DeskCounterparty, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Parties"],
    )
    @extend_schema(
        methods=["DELETE"],
        operation_id="parties_organizations_do_not_work_clear",
        summary="Remove the «do not work» mark",
        description="Х-8. Снять отметку «Не работать»; отметки нет — ничего не меняется (повтор безопасен). Тот же доступ.",
        request=None,
        responses={200: DeskCounterparty, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Parties"],
    )
    @action(detail=True, methods=["post", "delete"], url_path="do-not-work", url_name="do-not-work")
    def do_not_work(self, request, pk=None):
        company, client_ids = self._company(request, pk)
        if request.method == "DELETE":
            counterparty.clear_do_not_work(company, actor=request.user)
        else:
            body = DeskDoNotWorkIn(data=request.data)
            body.is_valid(raise_exception=True)
            try:
                counterparty.set_do_not_work(company, body.validated_data, actor=request.user)
            except ItemError as error:
                return refuse(error)
        company.refresh_from_db()
        return Response(counterparty.card(company, client_ids, request.user))
