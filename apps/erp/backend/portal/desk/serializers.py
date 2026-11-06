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
    contract_number = serializers.CharField(
        allow_blank=True,
        default="",
        help_text="Номер партнёрского договора (PART-ONBOARD-2).",
    )
    contract_date = serializers.DateField(
        allow_null=True,
        default=None,
        help_text="Дата партнёрского договора (PART-ONBOARD-2).",
    )
    invited_at = serializers.DateTimeField(allow_null=True)
    activated_at = serializers.DateTimeField(allow_null=True)
    suspended_at = serializers.DateTimeField(allow_null=True)
    responsible = DeskRef(allow_null=True)
    invited_by = DeskRef(allow_null=True)


class DeskSupplierAccessModules(serializers.Serializer):
    allowed = serializers.ListField(child=serializers.CharField(), help_text="Что шаблон роли разрешает включить.")
    default = serializers.ListField(child=serializers.CharField(), help_text="Что получает новое отношение.")


class DeskSupplierAccessCrmClient(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["none", "requested", "pending_confirmation", "held", "unverified", "linked", "conflict"],
        help_text=(
            "Клиент партнёра в CRM: `none` — не просили (партнёра ещё не приглашали), `requested` — ждём ответ CRM, `pending_confirmation` — CRM нашла похожего клиента и ждёт решения менеджера CRM, `held` — передача клиента из CRM нашла компанию по ИНН, заявки удержаны до сверки и повторного приглашения, `unverified` — сопоставление создала передача по совпадению ИНН и оно не проверено: сотрудник подтверждает («Да»/«Нет») здесь же, "
            "`linked` — заведён и сопоставлен, `conflict` — найденный клиент CRM занят другой компанией ERP."
        ),
    )
    crm_client_id = serializers.IntegerField(
        allow_null=True,
        help_text="Клиент CRM (`linked`, `conflict`): по нему Платформа строит ссылку «открыть клиента».",
    )
    crm_client_name = serializers.CharField(
        required=False, allow_null=True, help_text="`unverified`: как клиент назван в передаче из CRM."
    )
    inn = serializers.CharField(
        required=False, allow_null=True, help_text="`unverified`: ИНН, по которому компания связана с клиентом."
    )


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
    crm_client = DeskSupplierAccessCrmClient(
        help_text="Клиент партнёра в CRM (PART-CRM): партнёр становится клиентом CRM при приглашении."
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
    contract_number = serializers.CharField(required=False, allow_blank=True, max_length=64)
    contract_date = serializers.DateField(required=False, allow_null=True)


class DeskSupplierAccessRelationshipPatch(serializers.Serializer):
    modules = serializers.ListField(required=False, child=serializers.CharField())
    kind = serializers.CharField(required=False, allow_blank=True, max_length=20)
    contract_number = serializers.CharField(required=False, allow_blank=True, max_length=64)
    contract_date = serializers.DateField(required=False, allow_null=True)
    catalog_price_visibility = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=16,
        help_text="Пусто — как у компании; `cabinet` или `on_request`. Другое — 400 `VALIDATION_ERROR`.",
    )


# --- Заявки на партнёрство (PART-ONBOARD-2) ---


class DeskPartnerApplicationListItem(serializers.Serializer):
    id = serializers.IntegerField()
    source = serializers.ChoiceField(choices=["public", "client_cabinet"])
    status = serializers.ChoiceField(choices=["submitted", "contract_sent", "candidate_agreed", "approved", "rejected"])
    kind = serializers.CharField(allow_blank=True)
    company_name = serializers.CharField()
    country = serializers.CharField(allow_null=True, required=False)
    country_name = serializers.CharField(allow_null=True, required=False)
    inn = serializers.CharField(allow_blank=True)
    registration_number = serializers.CharField(allow_blank=True, required=False)
    contact_name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    language = serializers.ChoiceField(choices=["ru", "uz", "en"])
    categories_description = serializers.CharField()
    contract_number = serializers.CharField(allow_blank=True)
    contract_date = serializers.DateField(allow_null=True)
    contract_draft_sent_at = serializers.DateTimeField(allow_null=True, required=False)
    candidate_agreed_at = serializers.DateTimeField(allow_null=True, required=False)
    candidate_notes = serializers.CharField(allow_blank=True, required=False)
    has_contract_pdf = serializers.BooleanField(required=False, default=False)
    rejected_reason = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    reviewed_at = serializers.DateTimeField(allow_null=True)
    matching_company_id = serializers.IntegerField(allow_null=True)
    matching_company_name = serializers.CharField(allow_null=True)


class DeskPartnerApplicationDetail(DeskPartnerApplicationListItem):
    company_id = serializers.IntegerField(allow_null=True)
    applicant_contact_id = serializers.IntegerField(allow_null=True)
    reviewed_by = DeskRef(allow_null=True)


class DeskPartnerApplicationListResponse(serializers.Serializer):
    items = DeskPartnerApplicationListItem(many=True)
    pending_count = serializers.IntegerField(help_text="Количество заявок в статусе submitted")


class DeskPartnerApplicationSendContractIn(serializers.Serializer):
    contract_number = serializers.CharField(required=False, allow_blank=True, max_length=64)
    contract_date = serializers.DateField(required=False, allow_null=True)


class DeskPartnerApplicationApproveIn(serializers.Serializer):
    contract_number = serializers.CharField(
        required=True,
        min_length=1,
        max_length=64,
        help_text="Номер партнёрского договора (обязателен для завершения договорного шлюза).",
    )
    contract_date = serializers.DateField(required=False, allow_null=True)
    company_id = serializers.IntegerField(required=False, allow_null=True)
    kind = serializers.CharField(required=False, allow_blank=True, max_length=20)


class DeskPartnerApplicationRejectIn(serializers.Serializer):
    rejected_reason = serializers.CharField(
        required=True,
        min_length=1,
        max_length=1000,
        help_text="Причина отклонения заявки.",
    )
