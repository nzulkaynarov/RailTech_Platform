"""Схемы запросов и ответов доступа поставщика в кабинет (имена компонентов — `DeskSupplierAccess*`)."""

from rest_framework import serializers

from catalog.desk.serializers import DeskRef


class DeskSupplierAccessContact(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField()
    language = serializers.ChoiceField(choices=["ru", "uz", "en"])
    can_act = serializers.BooleanField(
        help_text="Может создавать запросы и загружать файлы (участник); иначе — просмотр."
    )
    invited_at = serializers.DateTimeField(allow_null=True)
    last_login_at = serializers.DateTimeField(allow_null=True)


class DeskSupplierAccessRelationship(serializers.Serializer):
    role = serializers.CharField(help_text="Роль отношения: `partner`.")
    kind = serializers.CharField(
        allow_blank=True,
        help_text="Вид партнёра — метка, на права не влияет: manufacturer, supplier, principal, other или пусто.",
    )
    modules = serializers.ListField(
        child=serializers.CharField(),
        help_text="Включённые партнёру модули кабинета (`my_products`, `catalog_requests`).",
    )
    catalog_price_visibility = serializers.ChoiceField(
        choices=["", "cabinet", "on_request"],
        help_text=(
            "Цены товаров партнёра в каталоге клиентов (PART-3): пусто — как у компании, `cabinet` — показывать, "
            "`on_request` — по запросу. Своя политика карточки сильнее."
        ),
    )
    status = serializers.ChoiceField(choices=["invited", "active", "suspended"])
    invited_at = serializers.DateTimeField(allow_null=True)
    activated_at = serializers.DateTimeField(allow_null=True)
    suspended_at = serializers.DateTimeField(allow_null=True)
    responsible = DeskRef(allow_null=True)
    invited_by = DeskRef(allow_null=True)


class DeskSupplierAccessModules(serializers.Serializer):
    allowed = serializers.ListField(child=serializers.CharField(), help_text="Что шаблон роли разрешает включить.")
    default = serializers.ListField(child=serializers.CharField(), help_text="Что получает новое отношение.")


class DeskSupplierAccess(serializers.Serializer):
    company_id = serializers.IntegerField()
    company_name = serializers.CharField()
    relationship = DeskSupplierAccessRelationship(
        allow_null=True, help_text="`null` — кабинет поставщику не открывали."
    )
    contacts = DeskSupplierAccessContact(many=True)
    partner_modules = DeskSupplierAccessModules()
    cabinet_roles = serializers.ListField(
        child=serializers.CharField(),
        help_text="Роли компании в кабинете сейчас: клиент (тип CLIENT) и/или партнёр (действующее отношение).",
    )
    cabinet_modules = serializers.ListField(
        child=serializers.CharField(), help_text="Разделы, которые откроются сессии компании."
    )
    can_manage = serializers.BooleanField(
        help_text="У сотрудника есть `supply.manage`: контакты, приглашение, приостановка."
    )


class DeskSupplierAccessContactIn(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    language = serializers.ChoiceField(required=False, choices=["ru", "uz", "en"])
    can_act = serializers.BooleanField(required=False, default=True)


class DeskSupplierAccessContactPatch(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=255)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    language = serializers.ChoiceField(required=False, choices=["ru", "uz", "en"])
    can_act = serializers.BooleanField(required=False)


class DeskSupplierAccessInviteIn(serializers.Serializer):
    contact_id = serializers.IntegerField(help_text="Контакт компании, которому уходит письмо с кодом входа.")
    modules = serializers.ListField(
        required=False,
        child=serializers.CharField(),
        help_text="Включённые модули; не указаны — у нового отношения значения по умолчанию.",
    )
    kind = serializers.CharField(required=False, allow_blank=True, max_length=20)


class DeskSupplierAccessRelationshipPatch(serializers.Serializer):
    modules = serializers.ListField(required=False, child=serializers.CharField())
    kind = serializers.CharField(required=False, allow_blank=True, max_length=20)
    catalog_price_visibility = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=16,
        help_text="Пусто — как у компании; `cabinet` или `on_request`. Другое — 400 `VALIDATION_ERROR`.",
    )
