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


class IsSupplierWithActiveSubscription(BasePermission):
    """
    Запись разрешена компаниям-поставщикам с активной/триальной подпиской.
    Администратор обходит проверку. Чтение свободно.
    """

    message = "SUBSCRIPTION_REQUIRED"

    def has_permission(self, request, view):
        user = request.user
        if request.method in SAFE_METHODS:
            return True
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        from accounts.models import SupplierSubscription

        supplier_company_ids = (
            user.memberships.filter(is_active=True).in_seller_company().values_list("company_id", flat=True)
        )
        subs = SupplierSubscription.objects.filter(company_id__in=list(supplier_company_ids))
        return any(s.is_operational for s in subs)


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

        # Seller team (can_sell): a seller may act on a CRM object IFF its deal is
        # ROUTED to one of their seller companies (multi-seller confidentiality —
        # replaces the old see-all where any seller could read any buyer's
        # deal/quote/chat). If not routed, fall through to the buyer-membership
        # check, so a dual seller+buyer can still reach their own buyer company's
        # objects while purchasing.
        # force=True: object access is context-INDEPENDENT (mirrors WP-1's list scope
        # for billing docs) — a routed seller who landed in the BUYER context must be
        # able to open/download the contract it can already see in the list. Routing
        # boundary preserved, so this never widens access to an unrelated deal.
        from accounts.services.permissions import is_seller, seller_can_access_deal

        if is_seller(user):
            deal_id = None
            if hasattr(obj, "seller_routings"):  # obj is a Deal
                deal_id = obj.pk
            elif hasattr(obj, "deal_id"):  # Quote / Invoice / Contract / Act
                deal_id = obj.deal_id
            elif hasattr(obj, "quote"):  # QuoteItem
                deal_id = obj.quote.deal_id
            if deal_id is not None and seller_can_access_deal(user, request, deal_id, force=True):
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
