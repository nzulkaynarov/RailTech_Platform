"""PortalAuthentication: аутентификация по cookie portal_session (или заголовку X-Portal-Session)."""

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db.models import F
from parties.models import active_contact_q
from rest_framework import authentication, exceptions

from .models import PortalSession
from .services.access import access_from_row, cabinet_company_q, role_annotations
from .services.tokens import hash_token


class PortalAuthentication(authentication.BaseAuthentication):
    """Аутентификация клиента портала.

    Читает cookie `portal_session` (или заголовок `X-Portal-Session`), валидирует `PortalSession`.
    При успехе прикрепляет к объекту request:
      - `request.portal_session`: PortalSession
      - `request.portal_contact`: Contact
      - `request.portal_company`: Company
      - `request.portal_roles`, `request.portal_modules`: роли (`client`, `partner`) и модули компании сессии — по модулю
        эндпоинт решает, кого пустить (`portal.permissions.HasPortalModule`); читаются тем же запросом, что и сессия
    Возвращает (AnonymousUser(), session).
    Сотрудники бэк-офиса изолированы: сессия сотрудника не дает доступа к порталу и наоборот.

    Живая сессия валидна, только пока валидны её основания (FIX-15, хвост ревью FIX-14): срок не вышел,
    компания допущена в кабинет (`cabinet_company_q`: не в архиве и клиент либо партнёр с действующим отношением; сняли
    тип CLIENT или приостановили отношение — сессия гаснет на следующем же запросе) и контакт всё ещё принадлежит компании сессии
    (контакт перевели или удалили — прежняя сессия не открывает чужие данные). Иначе 401, как без сессии.
    """

    def authenticate(self, request):
        cookie_name = getattr(settings, "PORTAL_SESSION_COOKIE_NAME", "portal_session")
        token = request.COOKIES.get(cookie_name)
        if not token:
            token = request.headers.get("X-Portal-Session") or request.META.get("HTTP_X_PORTAL_SESSION")

        if not token:
            return None

        session = (
            PortalSession.objects.filter(token_hash=hash_token(token))
            .filter(cabinet_company_q("company"), active_contact_q("contact"), company_id=F("contact__company_id"))
            .annotate(**role_annotations("company"))
            .select_related("contact", "company")
            .first()
        )

        if not session or not session.is_valid():
            raise exceptions.AuthenticationFailed("UNAUTHORIZED")

        request.portal_session = session
        request.portal_contact = session.contact
        request.portal_company = session.company
        request.portal_roles, request.portal_modules = access_from_row(session)

        return (AnonymousUser(), session)
