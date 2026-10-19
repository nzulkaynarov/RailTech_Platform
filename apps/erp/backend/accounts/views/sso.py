"""SSO API Views for ERP (CONTRACTS §6, packages/contracts/sso-token.md, M3-CRM-06).

Эндпоинты:
1. POST /api/v1/auth/sso/token — выдать токен для перехода в CRM (iss=erp, aud=crm).
2. POST /api/v1/auth/sso/exchange — обменять токен CRM (iss=crm, aud=erp) на сессию ERP.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from rest_framework import permissions, status, views
from rest_framework.response import Response

from accounts.services.sso import (
    SsoForbiddenError,
    SsoNotConfiguredError,
    SsoValidationError,
    issue_sso_token,
    verify_and_exchange_sso_token,
)
from accounts.services.tokens import refresh_for
from accounts.views.auth import _set_refresh_cookie

logger = logging.getLogger(__name__)


def _get_client_ip(request: Any) -> str:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or ""


class SsoIssueTokenView(views.APIView):
    """POST /api/v1/auth/sso/token — выдать токен для перехода в CRM."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            token, redirect_url = issue_sso_token(request.user)
            return Response(
                {
                    "token": token,
                    "redirect_url": redirect_url,
                },
                status=status.HTTP_200_OK,
            )
        except SsoForbiddenError as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_403_FORBIDDEN)
        except SsoNotConfiguredError as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception("Failed to issue SSO token: %s", exc)
            return Response({"detail": "SSO_ISSUE_FAILED"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SsoExchangeView(views.APIView):
    """POST /api/v1/auth/sso/exchange — обменять токен CRM на сессию ERP."""

    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        token = request.data.get("token")
        if not token:
            return Response({"detail": "TOKEN_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        client_ip = _get_client_ip(request)
        try:
            user, staff_user = verify_and_exchange_sso_token(token, client_ip=client_ip)
        except SsoValidationError as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_401_UNAUTHORIZED)
        except SsoForbiddenError as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_403_FORBIDDEN)
        except SsoNotConfiguredError as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception("Unexpected error during SSO exchange: %s", exc)
            return Response({"detail": "SSO_EXCHANGE_FAILED"}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = refresh_for(user)
        access_ttl = getattr(settings, "SIMPLE_JWT", {}).get("ACCESS_TOKEN_LIFETIME")
        expires_in = int(access_ttl.total_seconds()) if access_ttl else 3600

        data = {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "expires_in": expires_in,
            "user": staff_user,
        }
        response = Response(data, status=status.HTTP_200_OK)
        _set_refresh_cookie(response, str(refresh))
        return response
