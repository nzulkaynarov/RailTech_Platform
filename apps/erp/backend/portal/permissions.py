"""Portal permissions: IsPortalAuthenticated, HasPortalModule и CanAct (M2-ERP-01, ADR-0022)."""

from rest_framework import exceptions, permissions


class IsPortalAuthenticated(permissions.BasePermission):
    """Требует активной сессии клиентского портала."""

    message = "UNAUTHORIZED"

    def has_permission(self, request, view):
        if not getattr(request, "portal_session", None):
            raise exceptions.NotAuthenticated(self.message)
        return True


#: Эндпоинт открыт любой сессии кабинета (профиль). Явная отметка, а не отсутствие: вьюха без `required_module` закрыта.
ANY_MODULE = "*"


class HasPortalModule(permissions.BasePermission):
    """Модуль сессии: вьюха называет нужный модуль в `required_module` (или кортеж — достаточно любого), иначе 403.

    Модули сессии (`request.portal_modules`) — клиентские по типу компании плюс включённые партнёру на отношении
    (`portal/services/roles.py`); читаются на каждом запросе, поэтому включение и выключение модуля действует сразу, без
    перевхода. Вьюха без `required_module` закрыта всем (fail-closed): новый эндпоинт обязан назвать модуль, `ANY_MODULE`
    — только для профиля. Сессия партнёра без модуля получает 403 `MODULE_REQUIRED`.
    """

    message = "MODULE_REQUIRED"

    def has_permission(self, request, view):
        if not getattr(request, "portal_session", None):
            raise exceptions.NotAuthenticated("UNAUTHORIZED")
        required = getattr(view, "required_module", None)
        if required == ANY_MODULE:
            return True
        wanted = (required,) if isinstance(required, str) else tuple(required or ())
        if not set(wanted) & set(getattr(request, "portal_modules", ())):
            raise exceptions.PermissionDenied(self.message)
        return True


def _wanted_modules(view) -> tuple:
    required = getattr(view, "required_module", None)
    return (required,) if isinstance(required, str) else tuple(required or ())


class CanAct(permissions.BasePermission):
    """Требует права «действовать» (can_act=True) у контакта клиента.

    Если can_act=False, контакт имеет только доступ на чтение, мутации запрещены. Исключение — сессия партнёра без роли
    клиента в разделах, которые шаблон разрешает партнёру («Мои товары», «Каталог и заявки»): право «подписывать за
    компанию» там не нужно, партнёр заполняет свои карточки и создаёт заявки; КП, договоры, счета и акты ему закрыты
    модулем. Стала компания клиентом — снова решает `can_act`.
    """

    message = "FORBIDDEN"

    def has_permission(self, request, view):
        if not getattr(request, "portal_session", None):
            raise exceptions.NotAuthenticated("UNAUTHORIZED")
        if request.method in permissions.SAFE_METHODS:
            return True
        contact = getattr(request, "portal_contact", None)
        if contact and not contact.can_act and self._partner_scope(request, view):
            return True
        if not contact or not contact.can_act:
            raise exceptions.PermissionDenied(self.message)
        return True

    @staticmethod
    def _partner_scope(request, view) -> bool:
        from portal.services.roles import PARTNER, ROLE_MODULES

        wanted = _wanted_modules(view)
        roles = getattr(request, "portal_roles", ())
        return bool(wanted) and "client" not in roles and PARTNER in roles and set(wanted) <= set(ROLE_MODULES[PARTNER])
