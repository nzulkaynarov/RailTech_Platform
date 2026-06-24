from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.constants import SELLER_COMPANY_TYPES


class IsPlatformAdmin(BasePermission):
    """
    Разрешает доступ только Platform Admin — владельцу платформы.

    Инвариант: is_superuser ИЛИ носитель SystemRole='ADMIN' БЕЗ memberships.
    Регулирует всю платформу, не привязан ни к одной компании.
    """

    message = "Access restricted to platform administrators."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return user.is_platform_admin


class IsPlatformAdminOrReadOnly(BasePermission):
    """Публично читать, писать — только Platform Admin."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return user.is_platform_admin


class IsSupplierWithActiveSubscription(BasePermission):
    """
    Запись разрешена компаниям-поставщикам с активной/триальной подпиской.
    Platform Admin обходит проверку. Чтение свободно.
    """

    message = "Supplier subscription inactive or expired."

    def has_permission(self, request, view):
        user = request.user
        if request.method in SAFE_METHODS:
            return True
        if not (user and user.is_authenticated):
            return False
        if user.is_platform_admin:
            return True
        from accounts.models import SupplierSubscription

        supplier_company_ids = user.memberships.filter(
            is_active=True,
            company__types__code__in=SELLER_COMPANY_TYPES,
        ).values_list("company_id", flat=True)
        subs = SupplierSubscription.objects.filter(company_id__in=list(supplier_company_ids))
        return any(s.is_operational for s in subs)


class IsProductManagerOrAdmin(BasePermission):
    """
    Product edit rights:
      - Platform admin: full access.
      - Members of the product's owner_company (the seller that created the card):
        full access to their own products.
      - On create: any authenticated member of a SUPPLIER company.
    """

    message = "You can only manage products of your own company."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_platform_admin:
            return True
        if view.action == "create":
            return user.memberships.filter(
                is_active=True,
                company__types__code__in=SELLER_COMPANY_TYPES,
            ).exists()
        return True  # object-level check below for retrieve/update/delete

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_platform_admin:
            return True
        # Ownership moved from the deprecated `manufacturer` FK (always NULL now) to
        # `owner_company` (the seller that created the card). Falling back to the
        # legacy field covers any pre-split rows. The old code only checked
        # manufacturer_id → every seller got 403 editing their own product (H1).
        owner_id = getattr(obj, "owner_company_id", None) or getattr(obj, "manufacturer_id", None)
        if not owner_id:
            return False
        return user.memberships.filter(
            is_active=True,
            company_id=owner_id,
        ).exists()


class IsOfferSupplierOrAdmin(BasePermission):
    """Object-level guard for SupplierOffer writes (C2 tenant isolation):
      - Platform admin: full access.
      - Members of the offer's `supplier` company: edit/delete their own offers only.
    A seller must never be able to read or mutate a competitor's offer.
    """

    message = "You can only manage offers of your own company."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_platform_admin:
            return True
        return user.memberships.filter(is_active=True, company_id=obj.supplier_id).exists()


class IsCompanyMemberOrPlatformAdmin(BasePermission):
    """
    Object-level permission для мульти-тенантных ресурсов (Deal, Quote, Message, QuoteItem).

    - Platform Admin: полный доступ.
    - Остальные: доступ только к объектам своей компании (через CompanyMember).
    """

    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if user.is_platform_admin:
            return True

        # Seller team (can_sell) operates across all buyer заявки/deals in the
        # single-seller model — they are not members of the buyer's deal.company,
        # so grant access to CRM objects here (per-seller scoping comes with
        # multi-seller). Buyer-side access falls through to the membership check.
        from accounts.services.permissions import is_seller

        if is_seller(user):
            return True

        target_company = None
        if hasattr(obj, "company"):
            target_company = obj.company
        elif hasattr(obj, "deal"):
            target_company = obj.deal.company
        elif hasattr(obj, "quote"):
            target_company = obj.quote.deal.company
        elif obj == user:
            return True

        if target_company:
            return user.memberships.filter(company=target_company, is_active=True).exists()

        return False
