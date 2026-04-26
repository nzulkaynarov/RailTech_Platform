from rest_framework.permissions import SAFE_METHODS, BasePermission


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
            company__types__code__in=["SUPPLIER", "MANUFACTURER"],
        ).values_list("company_id", flat=True)
        subs = SupplierSubscription.objects.filter(company_id__in=list(supplier_company_ids))
        return any(s.is_operational for s in subs)


class IsProductManagerOrAdmin(BasePermission):
    """
    Product edit rights:
      - Platform admin: full access.
      - Members of the product.manufacturer company: full access to their own products.
      - On create: any authenticated member of a MANUFACTURER or SUPPLIER company.
    """

    message = "You can only manage products of your own manufacturer company."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_platform_admin:
            return True
        if view.action == "create":
            return user.memberships.filter(
                is_active=True,
                company__types__code__in=["MANUFACTURER", "SUPPLIER"],
            ).exists()
        return True  # object-level check below for retrieve/update/delete

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_platform_admin:
            return True
        manufacturer_id = getattr(obj, "manufacturer_id", None)
        if not manufacturer_id:
            return False
        return user.memberships.filter(
            is_active=True,
            company_id=manufacturer_id,
        ).exists()


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
