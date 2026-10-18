"""PortalAuthentication: аутентификация по cookie portal_session (или заголовку X-Portal-Session)."""

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework import authentication, exceptions

from .models import PortalSession
from .services.tokens import hash_token


class PortalAuthentication(authentication.BaseAuthentication):
    """Аутентификация клиента портала.

    Читает cookie `portal_session` (или заголовок `X-Portal-Session`), валидирует `PortalSession`.
    При успехе прикрепляет к объекту request:
      - `request.portal_session`: PortalSession
      - `request.portal_contact`: Contact
      - `request.portal_company`: Company
    Возвращает (AnonymousUser(), session).
    Сотрудники бэк-офиса изолированы: сессия сотрудника не дает доступа к порталу и наоборот.
    """

    def authenticate(self, request):
        cookie_name = getattr(settings, "PORTAL_SESSION_COOKIE_NAME", "portal_session")
        token = request.COOKIES.get(cookie_name)
        if not token:
            token = request.headers.get("X-Portal-Session") or request.META.get("HTTP_X_PORTAL_SESSION")

        if not token:
            return None

        session = (
            PortalSession.objects.filter(token_hash=hash_token(token)).select_related("contact", "company").first()
        )

        if not session or not session.is_valid():
            raise exceptions.AuthenticationFailed("UNAUTHORIZED")

        request.portal_session = session
        request.portal_contact = session.contact
        request.portal_company = session.company

        return (AnonymousUser(), session)
