from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status, views
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response

from accounts.serializers import (
    ForgotPasswordSerializer,
    RegisterInterestSerializer,
    ResetPasswordSerializer,
    SetupPasswordSerializer,
    SubmitProfileSerializer,
    UserSerializer,
)
from accounts.services import (
    create_pending_user,
    reset_password,
    revoke_user_refresh_tokens,
    send_password_reset_email,
    submit_company_profile,
    verify_and_setup_password,
)


@extend_schema(
    summary="Register new user",
    description=(
        "Register a new user by email. Creates an inactive user and sends "
        "a verification email with a password setup link."
    ),
    request=RegisterInterestSerializer,
    responses={
        201: OpenApiResponse(description="Verification email sent"),
        400: OpenApiResponse(description="Email already exists or validation error"),
    },
    tags=["Auth"],
)
class RegisterView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterInterestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = create_pending_user(
            email=serializer.validated_data["email"],
            first_name=serializer.validated_data["first_name"],
            last_name=serializer.validated_data["last_name"],
            phone=serializer.validated_data["phone"],
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Verification email sent.", "email": user.email}, status=status.HTTP_201_CREATED)


@extend_schema(
    summary="Setup password",
    description=(
        "Set a password for a newly registered user. Requires the uid and token "
        "from the verification email link. Activates the user account."
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

    def post(self, request):
        serializer = SetupPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = verify_and_setup_password(
            uidb64=serializer.validated_data["uid"],
            token=serializer.validated_data["token"],
            password=serializer.validated_data["password"],
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
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

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ok, error = send_password_reset_email(serializer.validated_data["email"])
        if error == "EMAIL_SEND_FAILED":
            return Response({"error": error}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
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

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = reset_password(
            uidb64=serializer.validated_data["uid"],
            token=serializer.validated_data["token"],
            password=serializer.validated_data["password"],
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Password has been reset.", "email": user.email})


@extend_schema(
    summary="Submit company profile",
    description=(
        "Minimal onboarding after registration. Creates a new Buyer (CLIENT) "
        "company and makes the user its OWNER. INN and selling are deferred."
    ),
    request=SubmitProfileSerializer,
    responses={
        200: OpenApiResponse(description="Profile submitted successfully"),
        400: OpenApiResponse(description="Validation error"),
    },
    tags=["Auth"],
)
class SubmitProfileView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SubmitProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = submit_company_profile(
            user=request.user,
            company_name=serializer.validated_data["companyName"],
            position=serializer.validated_data.get("position", ""),
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Profile submitted successful.", "user": UserSerializer(user).data})


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
    tags=["Auth"],
)
class LogoutView(views.APIView):
    """POST /api/v1/auth/logout/ — token revocation (was missing; access tokens
    are short-lived but a stolen refresh token lived for 7d with no kill switch)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import RefreshToken

        if request.data.get("all"):
            revoke_user_refresh_tokens(request.user)
            return Response(status=status.HTTP_205_RESET_CONTENT)

        token = request.data.get("refresh")
        if token:
            try:
                RefreshToken(token).blacklist()
            except TokenError:
                # Already expired/blacklisted/invalid — logout is idempotent.
                pass
        return Response(status=status.HTTP_205_RESET_CONTENT)


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
    tags=["Auth"],
)
class WsTicketView(views.APIView):
    """POST /api/v1/auth/ws-ticket/ — issues a one-time WS auth ticket."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        import secrets

        from django.core.cache import cache

        ticket = secrets.token_urlsafe(32)
        cache.set(f"ws_ticket:{ticket}", request.user.id, timeout=WS_TICKET_TTL)
        return Response({"ticket": ticket, "expires_in": WS_TICKET_TTL})
