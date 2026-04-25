from rest_framework import status, views, permissions
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse

from accounts.services import (
    create_pending_user, verify_and_setup_password,
    submit_company_profile,
    send_password_reset_email, reset_password,
)
from accounts.serializers import (
    RegisterInterestSerializer, SetupPasswordSerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer,
    SubmitProfileSerializer, UserSerializer,
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
    tags=['Auth'],
)
class RegisterView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterInterestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = create_pending_user(
            email=serializer.validated_data['email'],
            first_name=serializer.validated_data['first_name'],
            last_name=serializer.validated_data['last_name']
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Verification email sent.",
            "email": user.email
        }, status=status.HTTP_201_CREATED)


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
    tags=['Auth'],
)
class SetupPasswordView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SetupPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = verify_and_setup_password(
            uidb64=serializer.validated_data['uid'],
            token=serializer.validated_data['token'],
            password=serializer.validated_data['password']
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Password setup successful.",
            "user": UserSerializer(user).data
        })


@extend_schema(
    summary="Request password reset",
    description=(
        "Trigger a password-reset email. Always returns 200 to prevent user "
        "enumeration -- the caller should show the same outcome regardless of "
        "whether the email exists."
    ),
    request=ForgotPasswordSerializer,
    responses={200: OpenApiResponse(description="Reset email dispatched if account exists")},
    tags=['Auth'],
)
class ForgotPasswordView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ok, error = send_password_reset_email(serializer.validated_data['email'])
        if error == 'EMAIL_SEND_FAILED':
            return Response({'error': error}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        # Neutral 200 regardless of whether the email was found.
        return Response({'message': 'If an account exists, a reset link was sent.'})


@extend_schema(
    summary="Reset password",
    description="Complete a password reset using uid + token from the email link.",
    request=ResetPasswordSerializer,
    responses={
        200: OpenApiResponse(description="Password updated"),
        400: OpenApiResponse(description="Invalid token or weak password"),
    },
    tags=['Auth'],
)
class ResetPasswordView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = reset_password(
            uidb64=serializer.validated_data['uid'],
            token=serializer.validated_data['token'],
            password=serializer.validated_data['password'],
        )
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': 'Password has been reset.', 'email': user.email})


@extend_schema(
    summary="Submit company profile",
    description=(
        "Submit company profile after registration. Creates or links a Company "
        "by INN, assigns workspace role and company type."
    ),
    request=SubmitProfileSerializer,
    responses={
        200: OpenApiResponse(description="Profile submitted successfully"),
        400: OpenApiResponse(description="Validation error"),
    },
    tags=['Auth'],
)
class SubmitProfileView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SubmitProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = submit_company_profile(
            user=request.user,
            inn=serializer.validated_data['inn'],
            company_name=serializer.validated_data['companyName'],
            workspace_role_code=serializer.validated_data['role_code'],
            company_type_code=serializer.validated_data.get('company_type', 'CLIENT'),
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Profile submitted successful.",
            "user": UserSerializer(user).data
        })


@extend_schema(
    summary="Get current user profile",
    description="Returns the authenticated user's full profile including memberships and company data.",
    responses={200: UserSerializer},
    tags=['Accounts'],
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
