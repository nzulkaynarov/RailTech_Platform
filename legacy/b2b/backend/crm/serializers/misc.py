"""Message / Lead / ActivityLog serializers.

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor) — behaviour
unchanged.
"""

from rest_framework import serializers

from crm.audit_display import actor_display_name
from crm.models import ActivityLog, Lead, Message


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    is_me = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "deal",
            "seller_company",
            "sender",
            "sender_name",
            "text",
            "message_type",
            "timestamp",
            "is_me",
        ]
        # seller_company (the private lane) is resolved server-side from the sender's routing
        # / the buyer's selected counterparty — read-only here, never client-forgeable (audit #4).
        read_only_fields = ["sender", "timestamp", "message_type", "seller_company"]

    def get_sender_name(self, obj) -> str:
        sender = obj.sender
        if not sender:
            return ""
        full = sender.get_full_name()
        return full or sender.email

    def get_is_me(self, obj) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.sender_id == request.user.id
        return False


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = [
            "id",
            "name",
            "company",
            "phone",
            "email",
            "message",
            "is_processed",
            "created_at",
        ]
        read_only_fields = ["created_at", "is_processed"]


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    def get_user_name(self, obj) -> str:
        return actor_display_name(obj)

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "action",
            "detail",
            "event_code",
            "event_params",
            "user_name",
            "level",
            "timestamp",
        ]
