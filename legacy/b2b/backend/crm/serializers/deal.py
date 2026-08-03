"""Deal list/detail serializers + the viewer-scoped routing helpers.

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor) — behaviour
unchanged. The routing helpers enforce per-seller ownership visibility (a seller sees
only its own claim / itself among the routed sellers — hidden competition).
"""

from datetime import datetime

from rest_framework import serializers

from crm.models import Deal

from .quote import QuoteSerializer


def _viewer_routing(obj, request):
    """The DealSellerRouting for the VIEWER's OWN seller company on this deal (per-seller ownership,
    ADR-0006 Move 2). Each seller sees only THEIR company's claim — a competitor's routing is never
    surfaced, so cross-seller identity leakage is structurally impossible. Buyer / platform admin
    have no own-routing here → None (they don't claim)."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    company_ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    if not company_ids:
        return None
    return next(
        (r for r in obj.seller_routings.all() if r.seller_company_id in company_ids),
        None,
    )


def _assigned_to_id(obj, request):
    routing = _viewer_routing(obj, request)
    return routing.assigned_to_id if routing else None


def _assigned_to_display(obj, request):
    """Owner display name for the viewer's OWN company routing (their colleague), falling back to
    email since invited members often have a blank full name. None if unclaimed / not the viewer's.
    """
    routing = _viewer_routing(obj, request)
    if routing is None or not routing.assigned_to_id:
        return None
    assignee = routing.assigned_to
    return assignee.get_full_name() or assignee.email


def _assigned_at(obj, request):
    routing = _viewer_routing(obj, request)
    return routing.assigned_at if routing else None


def _viewer_is_seller(obj, request) -> bool:
    """Смотрит ли зритель на ЭТУ сделку со стороны продавца.

    Сторона — свойство ЗАПИСИ, а не сессии: одна и та же компания в одной сделке продавец, в
    другой покупатель. Фронт выводил её из `activeStatus` (= первый тип компании), и у компании
    с типами CLIENT+SUPPLIER продавец видел ПОКУПАТЕЛЬСКУЮ карточку своей же заявки — без
    кнопок подготовки КП (проход глазами 03-08).

    Бенчмарк: GitHub отдаёт `viewerCanUpdate`/`viewerDidAuthor` на каждом объекте, Salesforce —
    `UserRecordAccess`, Odoo Portal сверяет партнёра на сервере. Клиент роль ЧИТАЕТ, а не
    вычисляет. Тот же канон уже записан для пути «после контракта» (`DealSideResolver`).
    """
    return _viewer_routing(obj, request) is not None


def _viewer_is_buyer(obj, request) -> bool:
    """Смотрит ли зритель на эту сделку со стороны покупателя — членство в компании-заказчике.

    Платформенный оператор — наблюдатель (ADR-0002): ни одна из сторон ему не принадлежит.
    """
    from accounts.services import is_member_of, is_platform_admin_viewer

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if is_platform_admin_viewer(user):
        return False
    return bool(obj.company_id) and is_member_of(user, obj.company_id)


def _viewer_can_release(obj, request):
    """Может ли зритель вернуть эту сделку в очередь своей компании.

    Считает СЕРВЕР тем же предикатом, что и `release_deal`: владелец записи ИЛИ участник с
    правом `team.manage` в компании-продавце, которой сделка отроутена. Иначе фронт снова
    начал бы угадывать сторону по локальным флагам — ровно та ошибка, которую закрыла волна U1
    (виджет показывает объект, а право на действие выводит сам).

    Платформенный оператор — наблюдатель (ADR-0002): он не действует от имени компании.
    """
    from accounts.services import is_platform_admin_viewer, member_has_permission

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if is_platform_admin_viewer(user):
        return False
    routing = _viewer_routing(obj, request)
    # Возвращать нечего, пока запись никем не взята.
    if routing is None or not routing.assigned_to_id:
        return False
    if routing.assigned_to_id == user.id or getattr(user, "is_superuser", False):
        return True
    return member_has_permission(user, routing.seller_company_id, "team.manage")


def _target_sellers_for_viewer(obj, request):
    """Seller companies this RFQ is routed to — VIEWER-SCOPED (audit #5). The buyer (RFQ owner)
    and platform admin see the full routed set; a routed SELLER viewer sees only its OWN company,
    so a competitor never learns who else is bidding on the same заявка (hidden competition,
    ADR-0003 §5). Previously the full roster leaked to every routed seller."""
    sellers = list(obj.target_sellers.all())
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    as_dicts = [{"id": s.id, "name": s.name} for s in sellers]
    if getattr(user, "is_platform_admin", False):
        return as_dicts
    company_ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    # Buyer owns the RFQ → sees everyone it fanned out to; a seller sees only itself.
    if obj.company_id in company_ids:
        return as_dicts
    return [d for d in as_dicts if d["id"] in company_ids]


class DealListSerializer(serializers.ModelSerializer):
    """MED-3: Optimized list serializer with human-readable names."""

    stage_name = serializers.CharField(source="stage.name", read_only=True)
    stage_code = serializers.CharField(source="stage.code", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True, allow_null=True)
    # Offline client (Deal.contact) — so the send composer can name the recipient the backend
    # will actually resolve (resolve_quote_recipient falls back to the contact's email).
    contact_name = serializers.CharField(source="contact.name", read_only=True, allow_null=True)
    active_quote = QuoteSerializer(read_only=True)
    target_sellers_data = serializers.SerializerMethodField()
    # Per-seller ownership (ADR-0006 Move 2): these reflect the VIEWER's own company routing.
    assigned_to = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_at = serializers.SerializerMethodField()
    viewer_can_release = serializers.SerializerMethodField()
    # Сторона зрителя относительно ЭТОЙ сделки — считает сервер (см. `_viewer_is_seller`).
    viewer_is_seller = serializers.SerializerMethodField()
    viewer_is_buyer = serializers.SerializerMethodField()

    def get_viewer_is_seller(self, obj) -> bool:
        return _viewer_is_seller(obj, self.context.get("request"))

    def get_viewer_is_buyer(self, obj) -> bool:
        return _viewer_is_buyer(obj, self.context.get("request"))

    def get_assigned_to(self, obj) -> int | None:
        return _assigned_to_id(obj, self.context.get("request"))

    def get_assigned_to_name(self, obj) -> str | None:
        return _assigned_to_display(obj, self.context.get("request"))

    def get_assigned_at(self, obj) -> datetime | None:
        return _assigned_at(obj, self.context.get("request"))

    def get_viewer_can_release(self, obj) -> bool:
        return _viewer_can_release(obj, self.context.get("request"))

    def get_target_sellers_data(self, obj) -> list:
        """Seller companies this RFQ is routed to (multi-seller routing)."""
        return _target_sellers_for_viewer(obj, self.context.get("request"))

    class Meta:
        model = Deal
        fields = [
            "id",
            "title",
            "company",
            "company_name",
            "contact_name",
            "stage",
            "stage_code",
            "stage_name",
            "total_value",
            "manager",
            "assigned_to",
            "assigned_to_name",
            "assigned_at",
            "viewer_can_release",
            "viewer_is_seller",
            "viewer_is_buyer",
            "active_quote",
            "target_sellers_data",
            "created_at",
        ]


class DealDetailSerializer(serializers.ModelSerializer):
    """MED-3: Full detail serializer with quotes."""

    quotes = QuoteSerializer(many=True, read_only=True)
    active_quote = QuoteSerializer(read_only=True)
    stage_name = serializers.CharField(source="stage.name", read_only=True)
    stage_code = serializers.CharField(source="stage.code", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True, allow_null=True)
    # Offline client (Deal.contact) — so the send composer can name the recipient the backend
    # will actually resolve (resolve_quote_recipient falls back to the contact's email).
    contact_name = serializers.CharField(source="contact.name", read_only=True, allow_null=True)
    client_name = serializers.CharField(source="client.get_full_name", read_only=True)
    manager_name = serializers.CharField(source="manager.get_full_name", read_only=True)
    # Per-seller ownership (ADR-0006 Move 2): these reflect the VIEWER's own company routing.
    assigned_to = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_at = serializers.SerializerMethodField()
    viewer_can_release = serializers.SerializerMethodField()
    # Сторона зрителя относительно ЭТОЙ сделки — считает сервер (см. `_viewer_is_seller`).
    viewer_is_seller = serializers.SerializerMethodField()
    viewer_is_buyer = serializers.SerializerMethodField()
    can_edit_request = serializers.SerializerMethodField()
    target_sellers_data = serializers.SerializerMethodField()

    def get_viewer_is_seller(self, obj) -> bool:
        return _viewer_is_seller(obj, self.context.get("request"))

    def get_viewer_is_buyer(self, obj) -> bool:
        return _viewer_is_buyer(obj, self.context.get("request"))

    def get_assigned_to(self, obj) -> int | None:
        return _assigned_to_id(obj, self.context.get("request"))

    def get_assigned_to_name(self, obj) -> str | None:
        return _assigned_to_display(obj, self.context.get("request"))

    def get_assigned_at(self, obj) -> datetime | None:
        return _assigned_at(obj, self.context.get("request"))

    def get_viewer_can_release(self, obj) -> bool:
        return _viewer_can_release(obj, self.context.get("request"))

    def get_target_sellers_data(self, obj) -> list:
        """Seller companies this RFQ is routed to (multi-seller routing)."""
        return _target_sellers_for_viewer(obj, self.context.get("request"))

    def get_can_edit_request(self, obj) -> bool:
        """Whether the current user may add/edit/remove this deal's request rows."""
        from crm.services import buyer_can_edit_request

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return buyer_can_edit_request(obj, user)

    class Meta:
        model = Deal
        fields = [
            "id",
            "company",
            "company_name",
            "contact_name",
            "client",
            "client_name",
            "manager",
            "manager_name",
            "assigned_to",
            "assigned_to_name",
            "assigned_at",
            "viewer_can_release",
            "viewer_is_seller",
            "viewer_is_buyer",
            "stage",
            "stage_code",
            "stage_name",
            "title",
            "notes",
            "active_quote",
            "quotes",
            "can_edit_request",
            "target_sellers_data",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "company": {"required": False},
            "client": {"required": False},
        }
