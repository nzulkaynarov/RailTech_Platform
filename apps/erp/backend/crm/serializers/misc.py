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
            # Связь со сделкой и тип сущности — для ленты «Сегодня» Платформы (D2-0, Q-D20-1.3); столбцы самой строки,
            # обхода связей нет (`deal_id` — атрибут FK).
            "entity_type",
            "deal_id",
        ]
