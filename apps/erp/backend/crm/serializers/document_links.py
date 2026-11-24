"""Ссылки клиента на договор, счёт и акт в карточке Платформы (ДК-3б): список получателей и отзыв."""

from rest_framework import serializers


class DocumentRecipientLinkSerializer(serializers.Serializer):
    """Одна ссылка получателя; адрес только замаскированный."""

    id = serializers.IntegerField()
    recipient_hint = serializers.CharField(help_text="Адрес получателя, замаскированный: `a***@domain`")
    sent_at = serializers.DateTimeField(help_text="Когда ссылка выпущена (письмо ушло)")
    first_opened_at = serializers.DateTimeField(allow_null=True)
    last_opened_at = serializers.DateTimeField(allow_null=True)
    expires_at = serializers.DateTimeField()
    state = serializers.CharField(help_text="`active`, `revoked`, `expired` или `superseded`")


class DocumentClientLinksSerializer(serializers.Serializer):
    links = DocumentRecipientLinkSerializer(many=True)
    can_revoke = serializers.BooleanField(help_text="Есть живая ссылка, и у вызывающего есть право отправлять документ")
