from django.conf import settings
from django.contrib.auth import get_user_model
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import permissions, serializers, status, views
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


def _set_refresh_cookie(response, token: str) -> None:
    """Store the refresh token in an HttpOnly cookie (F2.1) — never exposed to JS."""
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        token,
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response) -> None:
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


from accounts.serializers import (  # noqa: E402
    ActiveSessionSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    SetupPasswordSerializer,
    UserSerializer,
)
from accounts.services import auth as auth_service  # noqa: E402
from accounts.services import (  # noqa: E402
    login_guard,
    reset_password,
    revoke_user_refresh_tokens,
    send_password_reset_email,
    sessions,
    two_factor,
    verify_and_setup_password,
)
from accounts.services.tokens import TOKEN_VERSION_CLAIM, refresh_for, token_version_of  # noqa: E402
from accounts.throttles import PasswordResetEmailThrottle, ScopedRateThrottle  # noqa: E402
from core.cache import UNAVAILABLE_MESSAGE, CacheUnavailable, fail_closed  # noqa: E402


@extend_schema(
    summary="Setup password",
    description=(
        "Set the first password of an invited user (team invitation or an account created "
        "by an administrator). Requires the uid and token from the email link. Activates the account."
    ),
    request=SetupPasswordSerializer,
    responses={
        200: OpenApiResponse(description="Password set, user activated"),
        400: OpenApiResponse(description="Invalid or expired token"),
    },
    tags=["Auth"],
)
class SetupPasswordView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_set"

    def post(self, request):
        serializer = SetupPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = verify_and_setup_password(
            uidb64=serializer.validated_data["uid"],
            token=serializer.validated_data["token"],
            password=serializer.validated_data["password"],
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Password setup successful.", "user": UserSerializer(user).data})


@extend_schema(
    summary="Request password reset",
    description=(
        "Trigger a password-reset email. Always returns 200 to prevent user "
        "enumeration -- the caller should show the same outcome regardless of "
        "whether the email exists."
    ),
    request=ForgotPasswordSerializer,
    responses={200: OpenApiResponse(description="Reset email dispatched if account exists")},
    tags=["Auth"],
)
class ForgotPasswordView(views.APIView):
    permission_classes = [permissions.AllowAny]
    # Two limits: per-IP (password_reset) AND per-target-email (password_reset_email)
    # so neither one IP nor IP-rotation can bomb a victim's inbox.
    throttle_classes = [ScopedRateThrottle, PasswordResetEmailThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ok, error = send_password_reset_email(serializer.validated_data["email"])
        if error == "EMAIL_SEND_FAILED":
            return Response({"detail": error}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        # Neutral 200 regardless of whether the email was found.
        return Response({"message": "If an account exists, a reset link was sent."})


@extend_schema(
    summary="Reset password",
    description="Complete a password reset using uid + token from the email link.",
    request=ResetPasswordSerializer,
    responses={
        200: OpenApiResponse(description="Password updated"),
        400: OpenApiResponse(description="Invalid token or weak password"),
    },
    tags=["Auth"],
)
class ResetPasswordView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_set"

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = reset_password(
            uidb64=serializer.validated_data["uid"],
            token=serializer.validated_data["token"],
            password=serializer.validated_data["password"],
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Password has been reset.", "email": user.email})


@extend_schema(
    summary="Get current user profile",
    description="Returns the authenticated user's full profile including memberships and company data.",
    responses={200: UserSerializer},
    tags=["Accounts"],
)
class MeView(RetrieveAPIView):
    """
    Retrieve the current authenticated user's profile.
    GET /api/v1/accounts/me/
    """

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


@extend_schema(
    summary="Log out (revoke refresh token)",
    description=(
        "Blacklist the supplied refresh token so it can no longer be used to mint "
        "access tokens. Pass `all: true` to revoke every refresh token for the "
        "current user (log out of all devices). Always succeeds (idempotent) — a "
        "missing/already-invalid token still returns 205."
    ),
    request=inline_serializer(
        "LogoutRequest",
        fields={
            "all": serializers.BooleanField(required=False),
            "refresh": serializers.CharField(required=False),
        },
    ),
    responses={205: OpenApiResponse(description="Logged out (idempotent)")},
    tags=["Auth"],
)
class LogoutView(views.APIView):
    """POST /api/v1/auth/logout/ — token revocation (was missing; access tokens
    are short-lived but a stolen refresh token lived for 7d with no kill switch)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.data.get("all"):
            revoke_user_refresh_tokens(request.user)
            resp = Response(status=status.HTTP_205_RESET_CONTENT)
            _clear_refresh_cookie(resp)
            return resp

        # Prefer the HttpOnly cookie (F2.1); fall back to the body for older clients.
        token = request.data.get("refresh") or request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if token:
            try:
                RefreshToken(token).blacklist()
            except TokenError:
                # Already expired/blacklisted/invalid — logout is idempotent.
                pass
        resp = Response(status=status.HTTP_205_RESET_CONTENT)
        _clear_refresh_cookie(resp)
        return resp


# Short-lived, single-use ticket TTL (seconds). Long enough to open the socket
# right after fetching, short enough that a leaked ticket (proxy/access logs) is
# useless almost immediately.
WS_TICKET_TTL = 30


@extend_schema(
    summary="Mint a one-time WebSocket auth ticket",
    description=(
        "Returns a short-lived, single-use ticket to authenticate a WebSocket "
        "connection (`?ticket=...`), so the long-lived JWT no longer travels in the "
        "WS URL query string (which proxies/CDNs log). The ticket is consumed on "
        "first use and expires in 30s."
    ),
    request=None,
    responses={
        200: inline_serializer(
            "WsTicket",
            fields={"ticket": serializers.CharField(), "expires_in": serializers.IntegerField()},
        )
    },
    tags=["Auth"],
)
class WsTicketView(views.APIView):
    """POST /api/v1/auth/ws-ticket/ — issues a one-time WS auth ticket."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        import secrets

        from django.core.cache import cache

        ticket = secrets.token_urlsafe(32)
        with fail_closed():  # билет, который негде хранить, не выдаём: 503 вместо билета, который не сработает (S0-2)
            cache.set(f"ws_ticket:{ticket}", request.user.id, timeout=WS_TICKET_TTL)
        return Response({"ticket": ticket, "expires_in": WS_TICKET_TTL})


# Пароль верен, но пользователь не сотрудник (участник компании-клиента) — 403 `STAFF_ONLY` ДО выпуска
# токенов (FIX-13); неверный пароль по-прежнему 401 и считается в блокировке.
class StaffOnlyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        auth_service.assert_staff_login(user)
        refresh = super().get_token(user)
        refresh[TOKEN_VERSION_CLAIM] = user.token_version  # отзыв доступа из CRM гасит и access (FIX-11)
        return refresh


@extend_schema(request=TokenObtainPairSerializer, responses=TokenObtainPairSerializer)  # схема — как у simplejwt
class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Login (token obtain) with two brute-force layers:

    * a per-IP throttle (`login` scope, 10/min) — blunts a single-source attack;
    * a per-ACCOUNT lockout (SEC-06, accounts/services/login_guard) — blunts a
      DISTRIBUTED attack (many IPs) against one victim account, which the per-IP
      throttle alone cannot stop.
    """

    serializer_class = StaffOnlyTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        email = (request.data.get("email") or "").strip()
        if login_guard.is_locked(email):
            return login_guard.locked_response()
        try:
            response = super().post(request, *args, **kwargs)
        except AuthenticationFailed:
            # Bad credentials / inactive account → count it against the lockout,
            # keyed on the source IP (BaseThrottle.get_ident mirrors the per-IP
            # `login` throttle's client-IP resolution, honouring NUM_PROXIES).
            login_guard.record_failure(email, BaseThrottle().get_ident(request))
            raise
        if response.status_code == status.HTTP_200_OK:
            login_guard.reset(email)
        return response


@extend_schema(request=TokenObtainPairSerializer, responses=TokenObtainPairSerializer)  # схема — как у simplejwt
class CookieTokenObtainPairView(ThrottledTokenObtainPairView):
    """Login that returns the access token in the body and the refresh token in an
    HttpOnly cookie (F2.1) — the refresh token is never exposed to JavaScript.

    2FA accounts: the password is verified through the SAME simplejwt path (so the
    per-IP throttle and SEC-06 lockout keep counting, and a wrong password behaves
    identically whether 2FA is on or not — no enumeration). On success the minted
    pair is voided and the client gets a short-lived ticket for /auth/login/2fa/."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code != status.HTTP_200_OK:
            return response
        refresh = response.data.pop("refresh", None)
        email = (request.data.get("email") or "").strip()
        user = get_user_model().objects.filter(email=email).first()
        if user and user.is_2fa_enabled:
            two_factor.void_refresh_token(refresh)
            return Response({"2fa_required": True, "temp_token": two_factor.issue_login_ticket(user)})
        if refresh:
            _set_refresh_cookie(response, refresh)
        return response


class CookieTokenRefreshView(TokenRefreshView):
    """Refresh using the HttpOnly cookie (F2.1). Reads the refresh token from the
    cookie (body still accepted for transition), returns a fresh access token in the
    body, and — with rotation on — sets the rotated refresh token back as the cookie.

    Refresh не продлевается тому, кто больше не сотрудник (FIX-13: `assert_staff_login` → 403
    `STAFF_ONLY`) и тому, чей доступ отозван (FIX-11: версия токена `tv` ≠ `token_version` → 401):
    токен, выданный раньше, чем закрыли вход, иначе жил бы 7 дней.

    Лимит частоты — свой scope `token_refresh` (FIX-64, N-2), а не общий анонимный."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "token_refresh"

    def _dead(self, detail: str, http_status: int) -> Response:
        # Dead token: answer AND clear the cookie, otherwise the browser replays it on every visit.
        response = Response({"detail": detail}, status=http_status)
        _clear_refresh_cookie(response)
        return response

    def post(self, request, *args, **kwargs):
        token = request.data.get("refresh") or request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not token:
            return Response({"detail": "NO_REFRESH_TOKEN"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            alive = RefreshToken(token)
            user = get_user_model().objects.get(pk=alive["user_id"])
        except (TokenError, KeyError, get_user_model().DoesNotExist):
            return self._dead("INVALID_REFRESH_TOKEN", status.HTTP_401_UNAUTHORIZED)
        if not user.is_active or token_version_of(alive) != user.token_version:
            return self._dead("INVALID_REFRESH_TOKEN", status.HTTP_401_UNAUTHORIZED)
        try:
            auth_service.assert_staff_login(user)
        except PermissionDenied as exc:
            return self._dead(str(exc.detail), status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data={"refresh": token})
        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, get_user_model().DoesNotExist):
            # A structurally valid token can still be dead: expired/blacklisted, or its
            # user no longer exists (rotation re-reads the user → DoesNotExist would
            # otherwise 500). Answer 401 AND clear the cookie, otherwise the browser
            # replays the dead token on every visit forever.
            return self._dead("INVALID_REFRESH_TOKEN", status.HTTP_401_UNAUTHORIZED)
        data = dict(serializer.validated_data)
        rotated = data.pop("refresh", None)  # present when ROTATE_REFRESH_TOKENS
        response = Response(data, status=status.HTTP_200_OK)
        if rotated:
            _set_refresh_cookie(response, rotated)
        return response


class TOTPSetupView(views.APIView):
    """POST /api/v1/auth/2fa/setup/ — mint a secret + otpauth URI for the QR code.
    Nothing persists until the user confirms a code via /auth/2fa/verify/."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "two_factor"

    @extend_schema(
        summary="Start 2FA setup",
        request=None,
        responses={
            200: inline_serializer(
                "TOTPSetup", fields={"secret": serializers.CharField(), "uri": serializers.CharField()}
            ),
            400: OpenApiResponse(description="2FA_ALREADY_ENABLED"),
        },
        tags=["Auth"],
    )
    def post(self, request):
        if request.user.is_2fa_enabled:
            return Response({"detail": "2FA_ALREADY_ENABLED"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(two_factor.generate_totp_setup(request.user))


class TOTPVerifyView(views.APIView):
    """POST /api/v1/auth/2fa/verify/ — confirm the scanned secret and enable 2FA."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "two_factor"

    @extend_schema(
        summary="Verify and enable 2FA",
        request=inline_serializer(
            "TOTPVerify",
            fields={
                "secret": serializers.CharField(),
                "code": serializers.CharField(),
                "current_password": serializers.CharField(),
            },
        ),
        responses={
            200: OpenApiResponse(description="2FA enabled"),
            400: OpenApiResponse(
                description="PASSWORD_REQUIRED | INVALID_PASSWORD | 2FA_CODE_REQUIRED | "
                "2FA_INVALID_CODE | 2FA_ALREADY_ENABLED"
            ),
        },
        tags=["Auth"],
    )
    def post(self, request):
        error = two_factor.enable_totp(
            request.user,
            request.data.get("secret"),
            request.data.get("code"),
            request.data.get("current_password"),
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "2FA_ENABLED"})


class TOTPDisableView(views.APIView):
    """POST /api/v1/auth/2fa/disable/ — turn 2FA off (requires a valid code)."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "two_factor"

    @extend_schema(
        summary="Disable 2FA",
        request=inline_serializer(
            "TOTPDisable",
            fields={"code": serializers.CharField(), "current_password": serializers.CharField()},
        ),
        responses={
            200: OpenApiResponse(description="2FA disabled (idempotent)"),
            400: OpenApiResponse(
                description="PASSWORD_REQUIRED | INVALID_PASSWORD | 2FA_CODE_REQUIRED | 2FA_INVALID_CODE"
            ),
        },
        tags=["Auth"],
    )
    def post(self, request):
        error = two_factor.disable_totp(
            request.user,
            request.data.get("code"),
            request.data.get("current_password"),
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "2FA_DISABLED"})


class TOTPLoginView(views.APIView):
    """POST /api/v1/auth/login/2fa/ — second login step: ticket + TOTP code → tokens.

    Same anti-brute-force layers as the password step: per-IP `login` throttle and
    the SEC-06 per-account lockout (a distributed grind on the 6-digit code counts
    exactly like distributed password failures). Refresh token goes to the HttpOnly
    cookie ONLY — never the body (F2.1)."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        summary="Complete login with a 2FA code",
        request=inline_serializer(
            "TOTPLogin", fields={"temp_token": serializers.CharField(), "code": serializers.CharField()}
        ),
        responses={
            200: OpenApiResponse(description="Access token in body; refresh in HttpOnly cookie"),
            400: OpenApiResponse(description="2FA_TICKET_INVALID | 2FA_INVALID_CODE"),
            429: OpenApiResponse(description="TOO_MANY_LOGIN_ATTEMPTS"),
        },
        tags=["Auth"],
    )
    def post(self, request):
        try:
            user, error = two_factor.redeem_login_ticket(request.data.get("temp_token"), request.data.get("code"))
        except CacheUnavailable:
            # Хранилище одноразовых меток (кэш) недоступно: вход не выполнен, билет и код не погашены (S0-2).
            return Response(
                {"detail": "2FA_TEMPORARILY_UNAVAILABLE", "message": UNAVAILABLE_MESSAGE},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if error == "2FA_TICKET_INVALID":
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        # The ticket resolved the account — a locked account answers 429 before
        # anything is revealed about the submitted code (no verification oracle).
        if login_guard.is_locked(user.email):
            return login_guard.locked_response()
        if error:  # 2FA_INVALID_CODE — charge the account's distributed-attack lockout
            login_guard.record_failure(user.email, BaseThrottle().get_ident(request))
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        login_guard.reset(user.email)
        refresh = refresh_for(user)
        response = Response({"access": str(refresh.access_token)})
        _set_refresh_cookie(response, str(refresh))
        return response


class SessionListView(views.APIView):
    """GET /api/v1/auth/sessions/ — live refresh-token sessions of the caller.

    Lives under /auth/ ON PURPOSE: the HttpOnly refresh cookie is path-scoped to
    settings.REFRESH_COOKIE_PATH (/api/v1/auth/), so only under this prefix does
    the browser send it and can two_factor.refresh_cookie_jti() resolve the
    CURRENT session. The first version sat at /accounts/users/me/sessions where
    the cookie never arrived: `is_current` was always false and revoke-all
    blacklisted the caller's own session too (DRF's test client ignores cookie
    paths, so tests never saw it). Pinned by test_active_sessions.py.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get active sessions",
        description=(
            "Live refresh tokens (sessions) for the current user. `is_current` marks "
            "the session whose refresh token sits in this browser's HttpOnly cookie."
        ),
        responses={200: inline_serializer("SessionResponse", fields={"sessions": ActiveSessionSerializer(many=True)})},
        tags=["Auth"],
    )
    def get(self, request):
        tokens = sessions.active_sessions(request.user)
        serializer = ActiveSessionSerializer(
            tokens, many=True, context={"current_jti": two_factor.refresh_cookie_jti(request)}
        )
        return Response({"sessions": serializer.data})


class SessionsRevokeOthersView(views.APIView):
    """POST /api/v1/auth/sessions/revoke-all/ — "log out everywhere else".

    Same cookie-path constraint as SessionListView: outside /auth/ the current
    jti is unresolvable and this endpoint would nuke the caller's own session.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Revoke all other sessions",
        description=(
            "Blacklist every live refresh token except the current browser's "
            '(identified by the HttpOnly cookie), i.e. "log out everywhere else".'
        ),
        request=None,
        responses={200: inline_serializer("SessionsRevoked", fields={"revoked": serializers.IntegerField()})},
        tags=["Auth"],
    )
    def post(self, request):
        revoked = sessions.revoke_other_sessions(request.user, keep_jti=two_factor.refresh_cookie_jti(request))
        return Response({"revoked": revoked})
