from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsPlatformAdmin(BasePermission):
    """
    Разрешает доступ только администратору ERP — `is_superuser`.

    Операторская плоскость B2B («SystemRole=ADMIN без членств» и роли операторов) удалена в M1-ERP-02:
    администрирование людей — в CRM (ARCHITECTURE §7), «Администратор» в CRM = суперпользователь ERP.
    """

    # Отказ обязан приходить КОДОМ: витрина переводит его по словарю `apiErrors`, а
    # человеческую фразу перевести нечем — `extractCode` (frontend/src/lib/apiError.ts)
    # требует UPPER_SNAKE, не находит его и печатает на экране системный `ERR_BAD_REQUEST`
    # от axios.
    message = "PLATFORM_ADMIN_REQUIRED"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(user.is_superuser)


class IsPlatformAdminOrReadOnly(BasePermission):
    """Публично читать, писать — только администратор (`is_superuser`)."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(user.is_superuser)


class IsSellerCatalogManager(BasePermission):
    """
    Запись — участнику компании-продавца с правом роли `catalog.manage`; администратор
    (`is_superuser`) — всегда. Чтение свободно.

    До M1-ERP-02 (волна 2) здесь стоял гейт «активная подписка поставщика»; монетизация
    платформы удалена — действие решают права роли.
    """

    message = "ROLE_NOT_PERMITTED"

    def has_permission(self, request, view):
        user = request.user
        if request.method in SAFE_METHODS:
            return True
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        from accounts.constants import Permission
        from accounts.services.permissions import member_has_permission

        seller_company_ids = (
            user.memberships.filter(is_active=True).in_seller_company().values_list("company_id", flat=True)
        )
        return any(member_has_permission(user, cid, Permission.CATALOG_MANAGE) for cid in seller_company_ids)


class IsProductManagerOrAdmin(BasePermission):
    """
    Product edit rights (N3: слой прав `catalog.manage` теперь ДЕЙСТВУЮЩИЙ, а не декоративный):
      - Администратор (`is_superuser`): полный доступ.
      - Seller: членство владельца + `catalog.manage` из CompanyRole (до N3 код проверялся
        только меню — «Наблюдатель» не видел «Номенклатуру», но правил карточки по прямому
        API). Legacy-фолбэк без CompanyRole сохраняется в member_has_permission
        (OWNER → всё; иначе can_sell).
    """

    message = "PRODUCT_OF_ANOTHER_COMPANY"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        if view.action == "create":
            from accounts.constants import Permission
            from accounts.services.permissions import member_has_permission

            seller_company_ids = (
                user.memberships.filter(is_active=True).in_seller_company().values_list("company_id", flat=True)
            )
            return any(member_has_permission(user, cid, Permission.CATALOG_MANAGE) for cid in seller_company_ids)
        return True  # object-level check below for retrieve/update/delete

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_superuser:
            return True
        # Ownership moved from the deprecated `manufacturer` FK (always NULL now) to
        # `owner_company` (the seller that created the card). Falling back to the
        # legacy field covers any pre-split rows. The old code only checked
        # manufacturer_id → every seller got 403 editing their own product (H1).
        owner_id = getattr(obj, "owner_company_id", None) or getattr(obj, "manufacturer_id", None)
        if not owner_id:
            return False
        from accounts.constants import Permission
        from accounts.services.permissions import member_has_permission

        return member_has_permission(user, owner_id, Permission.CATALOG_MANAGE)


class IsOfferSupplierOrAdmin(BasePermission):
    """Object-level guard for SupplierOffer writes (C2 tenant isolation):
      - Администратор (`is_superuser`): full access.
      - Members of the offer's `supplier` company: edit/delete their own offers only.
    A seller must never be able to read or mutate a competitor's offer.
    """

    message = "OFFER_OF_ANOTHER_COMPANY"

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        return user.memberships.filter(is_active=True, company_id=obj.supplier_id).exists()


class IsCompanyMemberOrPlatformAdmin(BasePermission):
    """
    Object-level permission для мульти-тенантных ресурсов (Deal, Quote, QuoteItem).

    - Администратор (`is_superuser`): полный доступ.
    - Остальные: доступ только к объектам своей компании (через CompanyMember).
    """

    message = "PERMISSION_DENIED"

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if user.is_superuser:
            return True

        # Staff of the own company — the seller of every deal (BUSINESS §3.3) — may reach any
        # CRM object; what they may DO is decided by role permissions in the services. Everyone
        # else (buyer accounts until M2-ERP-01) falls through to the company-membership check.
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
