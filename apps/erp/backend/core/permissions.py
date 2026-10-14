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


class IsProductManagerOrAdmin(BasePermission):
    """
    Product edit rights (N3: слой прав `catalog.manage` теперь ДЕЙСТВУЮЩИЙ, а не декоративный):
      - Администратор (`is_superuser`): полный доступ.
      - Сотрудник: право роли `catalog.manage` в компании-владельце карточки (M1-ERP-05 — только
        роли, без выводов из должности OWNER и флага can_sell).
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


class IsBackOfficeStaff(BasePermission):
    """Сотрудник бэк-офиса (активный участник своей компании) или администратор.

    Каталог бэк-офиса несёт внутренний слой (поставщики, себестоимость, спрос, ТН ВЭД) — он не
    для клиента и не для анонима (M1-ERP-07). Клиент видит каталог только опубликованным слоем
    (`catalog.published`) через портал и бота.
    """

    message = "BACKOFFICE_ONLY"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        from accounts.services.permissions import is_seller

        return is_seller(user)


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


# ──────────────────────────────────────────────────────────────────────────
# Декларативный гейт прав бэк-офиса (M1-ERP-05)
#
# Каждый эндпоинт мутации объявляет код права в `required_permissions` вьюхи: для ViewSet —
# по имени действия (`create`, `partial_update`, `send_to_client`…), для APIView — по методу
# (`POST`, `PATCH`…). Значение — код права, кортеж кодов («хотя бы одно»), или маркер:
#   ADMIN_ONLY     — только администратор (`is_superuser`); остальным 403 PLATFORM_ADMIN_REQUIRED;
#   SELF_SERVICE   — любой вошедший действует над СВОИМ (профиль, аватар); владение проверяет вьюха;
#   BUYER_ONLY     — шаг покупателя (акцепт КП, подпись за клиента…): сотруднику 403
#                    ROLE_NOT_PERMITTED, покупательскому аккаунту — дальше, решает сервис.
# Гейт работает в `check_permissions` — ДО поиска объекта, поэтому отказ не зависит от того,
# существует ли объект (и не раскрывает этого). Сервисы проверяют те же коды тем же
# `member_has_permission` — гейт единообразный порог, а не вторая логика.
#
# Покупательский аккаунт (участник компании-клиента, до M2-ERP-01) проходит гейт только на
# действиях из `buyer_actions` вьюхи — дальше его права решает сервис (`buyer_access`). На всех
# остальных мутациях бэк-офиса он получает 403 ROLE_NOT_PERMITTED.
# ──────────────────────────────────────────────────────────────────────────

ADMIN_ONLY = "@admin"
SELF_SERVICE = "@self"
BUYER_ONLY = "@buyer"
GATE_MARKERS = frozenset({ADMIN_ONLY, SELF_SERVICE, BUYER_ONLY})
ROLE_NOT_PERMITTED = "ROLE_NOT_PERMITTED"


def required_permission_key(view, request):
    """Ключ правила для запроса: имя действия ViewSet или HTTP-метод APIView."""
    return getattr(view, "action", None) or request.method


def _has_handler(view, request) -> bool:
    """Есть ли у вьюхи обработчик метода (ViewSet — действие в `action_map`, APIView — метод)."""
    method = request.method.lower()
    if method not in getattr(view, "http_method_names", ()):
        return False
    if hasattr(view, "action_map"):
        return getattr(view, "action", None) is not None
    return hasattr(view, method)


def required_permission_for(view, request):
    """Объявленное правило для мутации (или None для безопасного метода)."""
    if request.method in SAFE_METHODS or not _has_handler(view, request):
        return None  # метод без обработчика — ответит DRF (405), не роль
    rules = getattr(view, "required_permissions", None) or {}
    key = required_permission_key(view, request)
    if key not in rules:
        # Мутация без объявленного права закрыта (fail-closed): тест матрицы ролей не даст
        # такому эндпоинту появиться, а если появился — он не открыт молча.
        return ROLE_NOT_PERMITTED
    return rules[key]


class HasRolePermission(BasePermission):
    """DRF-разрешение по `required_permissions` вьюхи (см. блок выше)."""

    message = ROLE_NOT_PERMITTED

    def has_permission(self, request, view):
        rule = required_permission_for(view, request)
        user = request.user
        if rule is None or not (user and user.is_authenticated):
            return True  # безопасный метод или аноним — решает IsAuthenticated (401), не роль
        if user.is_superuser or rule == SELF_SERVICE:
            return True
        if rule == ADMIN_ONLY:
            self.message = IsPlatformAdmin.message
            return False
        from accounts.services.permissions import is_seller, staff_has_permission

        if is_seller(user):
            return rule not in (BUYER_ONLY, ROLE_NOT_PERMITTED) and staff_has_permission(user, rule)
        return required_permission_key(view, request) in getattr(view, "buyer_actions", ())


class RoleGatedViewMixin:
    """Подмешивается ПЕРВЫМ во вьюху с мутациями: гейт прав срабатывает до остальных
    `permission_classes` и до `get_object()`, даже если вьюха переопределяет `get_permissions`.

    Объявления на вьюхе:
      `required_permissions = {"create": "deal.manage", "approve": BUYER_ONLY, ...}`
      `buyer_actions = {"create", "approve"}` — переходно до M2-ERP-01.
    """

    required_permissions: dict = {}
    buyer_actions: frozenset = frozenset()

    def check_permissions(self, request):
        gate = HasRolePermission()
        if not gate.has_permission(request, self):
            self.permission_denied(request, message=gate.message, code=gate.message)
        super().check_permissions(request)
