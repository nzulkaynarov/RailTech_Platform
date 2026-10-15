"""Portal permissions: IsPortalAuthenticated и CanAct (M2-ERP-01)."""

from rest_framework import exceptions, permissions


class IsPortalAuthenticated(permissions.BasePermission):
    """Требует активной сессии клиентского портала."""

    message = "UNAUTHORIZED"

    def has_permission(self, request, view):
        if not getattr(request, "portal_session", None):
            raise exceptions.NotAuthenticated(self.message)
        return True


class CanAct(permissions.BasePermission):
    """Требует права «действовать» (can_act=True) у контакта клиента.

    Если can_act=False, контакт имеет только доступ на чтение, мутации запрещены.
    """

    message = "FORBIDDEN"

    def has_permission(self, request, view):
        if not getattr(request, "portal_session", None):
            raise exceptions.NotAuthenticated("UNAUTHORIZED")
        if request.method in permissions.SAFE_METHODS:
            return True
        contact = getattr(request, "portal_contact", None)
        if not contact or not contact.can_act:
            raise exceptions.PermissionDenied(self.message)
        return True
