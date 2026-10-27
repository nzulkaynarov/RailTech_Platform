from rest_framework import serializers

from .models import EmailTemplate, Notification


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
            # L1: машинная пара для локализации на клиенте; title/message — RU-fallback.
            "event_code",
            "event_params",
            "link",
            "deal",
            "is_read",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "event_code", "event_params"]


class EmailTemplateSerializer(serializers.ModelSerializer):
    """DB-editable email template — Platform-Operator admin CRUD."""

    updated_by_email = serializers.CharField(source="updated_by.email", read_only=True)

    class Meta:
        model = EmailTemplate
        fields = [
            "id",
            "key",
            # L2: язык оверрайда; пусто = применяется ко всем языкам.
            "language",
            "subject",
            "html_body",
            "text_body",
            "available_variables",
            "is_active",
            "updated_by",
            "updated_by_email",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_by", "updated_by_email", "updated_at"]


class EmailTemplatePreviewSerializer(serializers.Serializer):
    """Optional override context for preview/test-send. Empty = use SAMPLE context."""

    context = serializers.DictField(required=False)


class EmailTemplateTestSendSerializer(EmailTemplatePreviewSerializer):
    """Input for the test-send action: a single recipient email."""

    to_email = serializers.EmailField()


class EmailTemplatePreviewResultSerializer(serializers.Serializer):
    """Ответ предпросмотра: тема и тела письма, как их соберёт настоящий конвейер, и контекст, на котором собрано."""

    key = serializers.CharField()
    subject = serializers.CharField()
    text_body = serializers.CharField()
    html_body = serializers.CharField()
    context_used = serializers.DictField(help_text="Контекст рендера: образцовый или присланный `context`")


class EmailTemplateTestSendResultSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Статус записи EmailLog или UNKNOWN")
    email_log_id = serializers.IntegerField(allow_null=True)
    to_email = serializers.EmailField()


class _RenderFailureDetailsSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=["template_does_not_exist", "template_syntax_error"])
    message = serializers.CharField(help_text="Текст ошибки Django (до 300 символов)")


class EmailTemplateRenderErrorSerializer(serializers.Serializer):
    """Отказ предпросмотра: шаблон не собирается (D2-0)."""

    detail = serializers.CharField(help_text="EMAIL_TEMPLATE_RENDER_FAILED")
    details = _RenderFailureDetailsSerializer()
