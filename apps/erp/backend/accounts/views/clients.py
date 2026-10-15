"""Offline-client contacts API (CRM Phase B, spec-remaining-2026-07-07 §2.2).

The seller team's client-base contacts: scoped strictly to companies in the team's own book
(`seller_clients` — confidentiality boundary), creation goes through the `create_offline_client`
service (Rule 8: search-before-create de-dup, reachability guard).
"""

from drf_spectacular.utils import extend_schema, inline_serializer
from portal.services.invitation import invite_contact_to_portal
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Contact
from accounts.services import create_offline_client
from accounts.services.clients import seller_clients
from core.permissions import RoleGatedViewMixin


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
            "telegram_user_id",
            "telegram_username",
            "language",
            "preferred_channel",
            "can_act",
            "invited_at",
            "last_login_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "company",
            "company_name",
            "company_is_registered",
            "telegram_user_id",
            "invited_at",
            "last_login_at",
            "created_at",
        ]


class OfflineClientCreateSerializer(serializers.Serializer):
    """Flat write payload for the create action (nested read, flat write pattern)."""

    company_name = serializers.CharField(max_length=255)
    contact_name = serializers.CharField(max_length=255)
    inn = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    position = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    can_act = serializers.BooleanField(required=False, default=True)
    language = serializers.ChoiceField(choices=["ru", "uz", "en"], required=False, default="ru")
    preferred_channel = serializers.ChoiceField(choices=["email", "telegram", "both"], required=False, default="email")
    telegram_username = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


@extend_schema(tags=["Client Base"])
class ContactViewSet(RoleGatedViewMixin, viewsets.ModelViewSet):
    """Contacts of the seller team's OWN client book. Create = «завести офлайн-клиента»
    (company + contact in one step, via the service). No delete — history stays."""

    required_permissions = {
        "create": "deal.manage",
        "update": "deal.manage",
        "partial_update": "deal.manage",
        "destroy": "deal.manage",
        "invite": "deal.manage",
    }

    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Contact.objects.none()
        user = self.request.user
        queryset = Contact.objects.select_related("company")
        if getattr(user, "is_superuser", False):
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
        request=inline_serializer(
            name="ContactInviteRequest",
            fields={
                "channel": serializers.ChoiceField(choices=["email", "telegram", "both"], required=False),
                "language": serializers.ChoiceField(choices=["ru", "uz", "en"], required=False),
            },
        ),
        responses={
            200: inline_serializer(
                name="ContactInviteResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "contact_id": serializers.IntegerField(),
                    "channel": serializers.CharField(),
                    "email_sent": serializers.BooleanField(),
                    "invite_url": serializers.CharField(),
                    "telegram_url": serializers.CharField(allow_null=True),
                    "invited_at": serializers.DateTimeField(),
                },
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="invite")
    def invite(self, request, pk=None):
        """Пригласить контакт клиента в личный кабинет (M2-ERP-02)."""
        contact = self.get_object()
        channel = request.data.get("channel")
        language = request.data.get("language")

        result, error_code = invite_contact_to_portal(
            contact=contact,
            actor=request.user,
            channel=channel,
            language=language,
        )
        if error_code:
            return Response({"detail": error_code}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)
