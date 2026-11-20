"""Файл заявки клиента (СЦ-10): исходник заявки на сделке — что приложил клиент в кабинете или пришло с заявкой."""

from rest_framework import serializers


class RequestFileSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(help_text="Имя файла, как его приложил клиент")
    uploaded_at = serializers.DateTimeField()
