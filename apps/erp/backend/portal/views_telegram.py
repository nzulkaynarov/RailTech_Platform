"""Portal API: привязка Telegram самим контактом (NOTIFY-1, ADR-0023 п. 3; контракт `/me/telegram`, `/me/telegram-link`).

Настройка самого контакта: открыта любой сессии кабинета (модуль `profile` есть всегда) и не требует права «действовать».
Логика — `portal/services/telegram_link.py`; вьюхи только авторизуют и зовут сервис.
"""

from portal.permissions import ANY_MODULE, HasPortalModule, IsPortalAuthenticated
from portal.services.telegram_link import issue_telegram_link, request_telegram_unlink, telegram_status
from portal.views import BasePortalView
from rest_framework import status
from rest_framework.response import Response


class _ContactSettingView(BasePortalView):
    required_module = ANY_MODULE
    # Без CanAct: Telegram — личная настройка контакта, а не действие от имени компании.
    permission_classes = [IsPortalAuthenticated, HasPortalModule]


class TelegramStatusView(_ContactSettingView):
    """GET /me/telegram — статус по проекции; DELETE /me/telegram — запрос отключения в CRM (202)."""

    def get(self, request):
        return Response(telegram_status(request.portal_contact))

    def delete(self, request):
        return Response(request_telegram_unlink(request.portal_contact), status=status.HTTP_202_ACCEPTED)


class TelegramLinkView(_ContactSettingView):
    """POST /me/telegram-link — одноразовая ссылка `t.me/<бот>?start=<токен>` на 15 минут."""

    def post(self, request):
        link = issue_telegram_link(request.portal_contact)
        return Response(
            {"url": link.url, "expires_at": link.expires_at.isoformat().replace("+00:00", "Z")},
            status=status.HTTP_201_CREATED,
        )
