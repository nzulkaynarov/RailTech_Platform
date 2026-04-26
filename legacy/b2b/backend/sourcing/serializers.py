from rest_framework import serializers

from .models import Attachment


class AttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_email = serializers.CharField(source="uploaded_by.email", read_only=True, default=None)

    class Meta:
        model = Attachment
        fields = [
            "id",
            "file",
            "original_filename",
            "uploaded_by",
            "uploaded_by_email",
            "uploaded_at",
            "product",
            "deal",
            "message",
            "quote",
            "company",
        ]
        read_only_fields = [
            "id",
            "original_filename",
            "uploaded_by",
            "uploaded_by_email",
            "uploaded_at",
        ]
