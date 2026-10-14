"""ActivityLog serializer.

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor) — behaviour
unchanged.
"""

from rest_framework import serializers

from crm.audit_display import actor_display_name
from crm.models import ActivityLog


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
