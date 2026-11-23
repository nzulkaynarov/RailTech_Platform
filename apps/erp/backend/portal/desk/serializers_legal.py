"""Схемы редакций оферты и политики Кабинета для «Настроек» Платформы (ДВ-5; имена компонентов — `DeskLegal*`)."""

from rest_framework import serializers


class DeskLegalText(serializers.Serializer):
    ru = serializers.CharField(allow_blank=True)
    uz = serializers.CharField(allow_blank=True)
    en = serializers.CharField(allow_blank=True)


class DeskLegalSection(serializers.Serializer):
    title = DeskLegalText()
    body = DeskLegalText(help_text="Абзацы через перевод строки; пункты списка начинаются с «— ».")


class DeskLegalContent(serializers.Serializer):
    title = DeskLegalText()
    lead = DeskLegalText()
    sections = DeskLegalSection(many=True)


class DeskLegalEditionRow(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["privacy", "terms"])
    label = serializers.CharField()
    status = serializers.ChoiceField(choices=["draft", "current", "retired"])
    created_at = serializers.DateTimeField()
    published_at = serializers.DateTimeField(allow_null=True)
    published_by = serializers.CharField(allow_blank=True)
    retired_at = serializers.DateTimeField(allow_null=True)
    acceptances_count = serializers.IntegerField()


class DeskLegalEditionList(serializers.Serializer):
    results = DeskLegalEditionRow(many=True)


class DeskLegalEditionDetail(DeskLegalEditionRow):
    content = DeskLegalContent(help_text="Текст как написан, с подстановками `{{company.*}}`.")
    rendered = DeskLegalContent(help_text="Тот же текст с подстановками из реквизитов компании — как увидит контакт.")


class DeskLegalEditionCreateIn(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["privacy", "terms"])


class DeskLegalEditionUpdateIn(serializers.Serializer):
    label = serializers.CharField(required=False, max_length=40)
    content = DeskLegalContent(required=False)


class DeskLegalAcceptanceContact(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True)
    email = serializers.CharField(allow_blank=True)


class DeskLegalAcceptanceCompany(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class DeskLegalAcceptance(serializers.Serializer):
    id = serializers.IntegerField()
    accepted_at = serializers.DateTimeField()
    kind = serializers.ChoiceField(choices=["privacy", "terms"])
    edition = serializers.CharField()
    edition_id = serializers.IntegerField()
    language = serializers.ChoiceField(choices=["ru", "uz", "en"])
    auth_method = serializers.CharField(allow_blank=True)
    contact = DeskLegalAcceptanceContact()
    company = DeskLegalAcceptanceCompany()
