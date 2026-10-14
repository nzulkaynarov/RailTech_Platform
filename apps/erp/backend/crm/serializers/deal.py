"""Deal list/detail serializers + the viewer-side helpers.

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor). The seller of every deal is the
own company (BUSINESS §3.3), so the deal owner (`Deal.assigned_to`) is one per deal and the
viewer's side is «staff of the own company» vs «member of the client company».
"""

from datetime import datetime

from rest_framework import serializers

from crm.models import Deal

from .quote import QuoteSerializer


def _authenticated_user(request):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return user


def _viewer_is_staff(request) -> bool:
    """Сотрудник компании-владельца (или администратор). Считается один раз на запрос — список
    сделок спрашивает это для каждой строки."""
    user = _authenticated_user(request)
    if user is None:
        return False
    cached = getattr(request, "_viewer_is_staff", None)
    if cached is None:
        from accounts.services import sees_all_deals

        cached = sees_all_deals(user)
        try:
            request._viewer_is_staff = cached
        except AttributeError:
            pass
    return cached


def _assigned_to_display(obj):
    """Owner display name, falling back to email since invited members often have a blank full
    name. None if unclaimed."""
    if not obj.assigned_to_id:
        return None
    assignee = obj.assigned_to
    return assignee.get_full_name() or assignee.email


def _viewer_is_seller(obj, request) -> bool:
    """Смотрит ли зритель на ЭТУ сделку со стороны продавца — то есть он сотрудник своей компании.

    Сторону считает СЕРВЕР, клиент её ЧИТАЕТ (GitHub `viewerCanUpdate`, Salesforce
    `UserRecordAccess`, Odoo Portal сверяет партнёра на сервере).
    """
    return _viewer_is_staff(request)


def _viewer_is_buyer(obj, request) -> bool:
    """Смотрит ли зритель на эту сделку со стороны покупателя — членство в компании-заказчике
    (покупательские аккаунты — до M2-ERP-01)."""
    from accounts.services import is_member_of

    user = _authenticated_user(request)
    if user is None:
        return False
    return bool(obj.company_id) and is_member_of(user, obj.company_id)


def _viewer_can_release(obj, request):
    """Может ли зритель вернуть эту сделку в очередь.

    Считает СЕРВЕР тем же предикатом, что и `release_deal`: владелец записи ИЛИ сотрудник с
    правом `team.manage` в своей компании (или администратор).
    """
    from accounts.services import member_has_permission, primary_seller_company_id

    user = _authenticated_user(request)
    # Возвращать нечего, пока запись никем не взята.
    if user is None or not obj.assigned_to_id:
        return False
    if obj.assigned_to_id == user.id or getattr(user, "is_superuser", False):
        return True
    company_id = primary_seller_company_id(user)
    return bool(company_id) and member_has_permission(user, company_id, "deal.assign")


class DealListSerializer(serializers.ModelSerializer):
    """MED-3: Optimized list serializer with human-readable names."""

    stage_name = serializers.CharField(source="stage.name", read_only=True)
    stage_code = serializers.CharField(source="stage.code", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True, allow_null=True)
    # Offline client (Deal.contact) — so the send composer can name the recipient the backend
    # will actually resolve (resolve_quote_recipient falls back to the contact's email).
    contact_name = serializers.CharField(source="contact.name", read_only=True, allow_null=True)
    active_quote = QuoteSerializer(read_only=True)
    execution_complete = serializers.SerializerMethodField()
    # Deal owner in the back office (ADR-0006 Move 2): one per deal — the seller is the own company.
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
        return obj.assigned_to_id

    def get_assigned_to_name(self, obj) -> str | None:
        return _assigned_to_display(obj)

    def get_assigned_at(self, obj) -> datetime | None:
        return obj.assigned_at

    def get_viewer_can_release(self, obj) -> bool:
        return _viewer_can_release(obj, self.context.get("request"))

    def get_execution_complete(self, obj) -> bool:
        """Исполнение закрыто целиком (оплата + поставка + акт) — НЕ то же, что «сделка выиграна».

        O4: `CLOSED_WON` наступает при подписании договора, когда покупателю ещё платить и
        принимать. Слово «Завершено» в интерфейсе опирается на этот флаг, а не на стадию.
        """
        from crm.services.deal_documents import deal_execution_is_complete

        return deal_execution_is_complete(obj)

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
            "execution_complete",
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
    # Deal owner in the back office (ADR-0006 Move 2): one per deal — the seller is the own company.
    assigned_to = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_at = serializers.SerializerMethodField()
    viewer_can_release = serializers.SerializerMethodField()
    # Сторона зрителя относительно ЭТОЙ сделки — считает сервер (см. `_viewer_is_seller`).
    viewer_is_seller = serializers.SerializerMethodField()
    viewer_is_buyer = serializers.SerializerMethodField()
    can_edit_request = serializers.SerializerMethodField()
    execution_complete = serializers.SerializerMethodField()

    def get_viewer_is_seller(self, obj) -> bool:
        return _viewer_is_seller(obj, self.context.get("request"))

    def get_viewer_is_buyer(self, obj) -> bool:
        return _viewer_is_buyer(obj, self.context.get("request"))

    def get_assigned_to(self, obj) -> int | None:
        return obj.assigned_to_id

    def get_assigned_to_name(self, obj) -> str | None:
        return _assigned_to_display(obj)

    def get_assigned_at(self, obj) -> datetime | None:
        return obj.assigned_at

    def get_viewer_can_release(self, obj) -> bool:
        return _viewer_can_release(obj, self.context.get("request"))

    def get_execution_complete(self, obj) -> bool:
        """Исполнение закрыто целиком (оплата + поставка + акт) — НЕ то же, что «сделка выиграна».

        O4: `CLOSED_WON` наступает при подписании договора, когда покупателю ещё платить и
        принимать. Слово «Завершено» в интерфейсе опирается на этот флаг, а не на стадию.
        """
        from crm.services.deal_documents import deal_execution_is_complete

        return deal_execution_is_complete(obj)

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
            "execution_complete",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "company": {"required": False},
            "client": {"required": False},
        }
