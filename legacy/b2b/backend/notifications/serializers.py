from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    type_code = serializers.CharField(source="type.code", read_only=True)
    type_name = serializers.CharField(source="type.name", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "user",
            "type",
            "type_code",
            "type_name",
            "title",
            "message",
            "link",
            "deal",
            "is_read",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
