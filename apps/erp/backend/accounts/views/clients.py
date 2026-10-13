"""Offline-client contacts API (CRM Phase B, spec-remaining-2026-07-07 §2.2).

The seller team's client-base contacts: scoped strictly to companies in the team's own book
(`seller_clients` — confidentiality boundary), creation goes through the `create_offline_client`
service (Rule 8: search-before-create de-dup, reachability guard).
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.models import Contact
from accounts.services import create_offline_client
from accounts.services.clients import seller_clients, send_client_invite


class ContactSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    company_is_registered = serializers.BooleanField(source="company.is_registered", read_only=True)

    class Meta:
        model = Contact
        fields = [
            "id",
            "company",
            "company_name",
            "company_is_registered",
            "name",
            "email",
            "phone",
            "position",
            "is_primary",
            "created_at",
        ]
        read_only_fields = ["id", "company", "company_name", "company_is_registered", "created_at"]


class OfflineClientCreateSerializer(serializers.Serializer):
    """Flat write payload for the create action (nested read, flat write pattern)."""

    company_name = serializers.CharField(max_length=255)
    contact_name = serializers.CharField(max_length=255)
    inn = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    position = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


@extend_schema(tags=["Client Base"])
class ContactViewSet(viewsets.ModelViewSet):
    """Contacts of the seller team's OWN client book. Create = «завести офлайн-клиента»
    (company + contact in one step, via the service). No delete — history stays."""

    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Contact.objects.none()
        user = self.request.user
        queryset = Contact.objects.select_related("company")
        if getattr(user, "is_superuser", False) or getattr(user, "is_superuser", False):
            return queryset
        return queryset.filter(company__in=seller_clients(user))

    @extend_schema(request=OfflineClientCreateSerializer, responses={201: ContactSerializer})
    def create(self, request, *args, **kwargs):
        payload = OfflineClientCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result, error_code = create_offline_client(seller=request.user, **payload.validated_data)
        if error_code:
            return Response({"detail": error_code}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ContactSerializer(result["contact"]).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Invite an offline client to register",
        description="CRM Phase D: email this contact an invite to register and CLAIM its existing "
        "offline company (no duplicate). Throttled per user.",
        request=None,
        responses={200: OpenApiResponse(description="{invited: true}"), 400: OpenApiResponse(description="error code")},
        tags=["Client Base"],
    )
    @action(detail=True, methods=["post"], throttle_classes=[ScopedRateThrottle])
    def invite(self, request, pk=None):
        _invite, error = send_client_invite(seller=request.user, contact_id=pk)
        if error:
            code = status.HTTP_404_NOT_FOUND if error == "CONTACT_NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=code)
        return Response({"invited": True})

    invite.throttle_scope = "client_invite"
