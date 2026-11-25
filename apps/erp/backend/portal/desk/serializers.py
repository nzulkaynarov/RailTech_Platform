"""Схемы запросов и ответов доступа поставщика в кабинет (имена компонентов — `DeskSupplierAccess*`)."""

from parties.do_not_work import DoNotWorkFacts
from rest_framework import serializers

from catalog.desk.serializers import DeskRef


class DeskSupplierAccessContact(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField()
    language = serializers.ChoiceField(choices=["ru", "uz", "en"])
    can_act = serializers.BooleanField(help_text="Может подтверждать (участник); иначе — просмотр.")
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
    can_act = serializers.BooleanField(
        required=False,
        help_text="Право контакта подтверждать заказы поставщику (в Кабинете и в Платформе — «Может подтверждать»); не указано — не меняется.",
    )


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


class DeskPartnerContractFacts(serializers.Serializer):
    """ПД-1: договорная часть карточки заявки — всё выведено из фактов заявки."""

    contract_source = serializers.ChoiceField(
        choices=["", "template", "upload"],
        help_text="Откуда договор: шаблон библиотеки или свой файл; пусто — не подготовлен.",
    )
    contract_template_id = serializers.IntegerField(allow_null=True)
    contract_template_name = serializers.CharField(allow_null=True)
    contract_template_edition = serializers.IntegerField(allow_null=True)
    contract_language = serializers.CharField(allow_blank=True)
    contract_deviation_text = serializers.CharField(allow_blank=True)
    contract_approval = serializers.ChoiceField(
        choices=["", "requested", "approved", "returned"],
        help_text="Согласование держателем «Право»: пусто — не требуется (шаблон без отступлений).",
    )
    contract_approval_requested_by = serializers.CharField(allow_null=True)
    contract_approval_decided_by = serializers.CharField(allow_null=True)
    contract_approval_note = serializers.CharField(allow_blank=True)
    contract_blocker = serializers.ChoiceField(
        choices=["CONTRACT_NOT_PREPARED", "CONTRACT_APPROVAL_PENDING", "CONTRACT_APPROVAL_RETURNED"],
        allow_null=True,
        help_text="Что мешает отправить договор (только пока заявка в статусе submitted); null — можно отправлять.",
    )
    candidate_returned_at = serializers.DateTimeField(allow_null=True)
    has_signed_scan = serializers.BooleanField()
    signed_scan_at = serializers.DateTimeField(allow_null=True)
    can_decide_contract = serializers.BooleanField(
        help_text="Зритель вправе решить: держатель права утверждать договоры; подготовивший — только если нет другого."
    )
    decision_needs_confirmation = serializers.BooleanField(
        help_text="Зритель — единственный держатель права и сам подготовил договор: решение с подтверждением."
    )
    contract_approvers = serializers.ListField(
        child=serializers.CharField(), help_text="Кто решает, пока согласование ждёт решения."
    )


class DeskPartnerApplicationListItem(DeskPartnerContractFacts):
    id = serializers.IntegerField()
    source = serializers.ChoiceField(
        choices=["public", "client_cabinet", "letter"],
        help_text="Заявка из карточки лида CRM отдаётся как `letter` с `from_lead = true` (перечень не растёт: ERP SPA и BFF читают его строго).",
    )
    from_lead = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Заявка заведена из карточки лида CRM (ЛП-1): `source_ref` — номер лида",
    )
    source_ref = serializers.CharField(
        allow_blank=True, required=False, help_text="Номер ВХ, если заявку завёл сотрудник по письму (план 1.9)"
    )
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
    company_match_pending = serializers.ChoiceField(
        choices=["inn", "registration_number"],
        allow_null=True,
        help_text="По какому ключу найдена существующая компания, пока сотрудник не решил, та ли это компания; иначе null.",
    )
    invite_delivery = serializers.ChoiceField(
        choices=["queued", "sent", "failed"],
        allow_null=True,
        help_text="Итог последнего письма-приглашения кандидату; null — приглашения ещё не было.",
    )


class DeskPartnerApplicationDetail(DeskPartnerApplicationListItem):
    company_id = serializers.IntegerField(allow_null=True)
    applicant_contact_id = serializers.IntegerField(allow_null=True)
    reviewed_by = DeskRef(allow_null=True)


class DeskPartnerApplicationCreateIn(serializers.Serializer):
    """Заявка кандидата по входящему письму (план 1.9, «Передать в работу»): заводит сотрудник снабжения."""

    company_name = serializers.CharField(max_length=255)
    inn = serializers.CharField(max_length=32, allow_blank=True, required=False, default="")
    country = serializers.CharField(max_length=2, required=False, default="UZ")
    kind = serializers.ChoiceField(
        choices=["manufacturer", "supplier", "principal", "other"], required=False, default="supplier"
    )
    categories_description = serializers.CharField(max_length=4000)
    contact_name = serializers.CharField(max_length=255)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=32, allow_blank=True, required=False, default="")
    language = serializers.ChoiceField(choices=["ru", "uz", "en"], required=False, default="ru")
    source_ref = serializers.CharField(max_length=32, help_text="Номер входящего письма")


class DeskPartnerApplicationListResponse(serializers.Serializer):
    items = DeskPartnerApplicationListItem(many=True)
    pending_count = serializers.IntegerField(help_text="Заявки, ждущие сотрудника: submitted и candidate_agreed")


class DeskPartnerApplicationSendContractIn(serializers.Serializer):
    """Отправка подготовленного договора (ПД-1): номер и дата заданы при подготовке и здесь не меняются."""

    contract_number = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="Не используется: номер задаётся при подготовке договора.",
    )
    contract_date = serializers.DateField(
        required=False, allow_null=True, help_text="Не используется: дата задаётся при подготовке договора."
    )
    company_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Сотрудник подтвердил: заявка от этой существующей компании."
    )
    create_new_company = serializers.BooleanField(
        required=False, default=False, help_text="Сотрудник подтвердил: найденная компания — другая, завести новую."
    )


class DeskPartnerApplicationApproveIn(serializers.Serializer):
    contract_number = serializers.CharField(
        required=True,
        min_length=1,
        max_length=64,
        help_text="Номер партнёрского договора (обязателен для завершения договорного шлюза).",
    )
    contract_date = serializers.DateField(required=False, allow_null=True)
    company_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Сотрудник подтвердил: заявка от этой существующей компании."
    )
    create_new_company = serializers.BooleanField(
        required=False, default=False, help_text="Сотрудник подтвердил: найденная компания — другая, завести новую."
    )
    kind = serializers.CharField(required=False, allow_blank=True, max_length=20)
    override_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="Причина одобрения без согласия кандидата; пишется в журнал. Без неё нужен статус candidate_agreed.",
    )


class DeskPartnerTemplateOption(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    edition = serializers.IntegerField()
    languages = serializers.ListField(child=serializers.ChoiceField(choices=["ru", "en", "uz"]))
    is_default = serializers.BooleanField()


class DeskPartnerContractOptions(serializers.Serializer):
    """Что выбрать при «Подготовить договор»: утверждённые партнёрские шаблоны библиотеки и правила компании."""

    templates = DeskPartnerTemplateOption(many=True)
    default_template_id = serializers.IntegerField(allow_null=True)
    deviations_allowed = serializers.BooleanField()
    approvers = serializers.ListField(child=serializers.CharField(), help_text="Держатели зоны «Право» по имени.")
    can_decide = serializers.BooleanField()


class DeskPartnerContractPrepareIn(serializers.Serializer):
    """Договор из шаблона (`template_id` или умолчание настроек) либо свой файл (`file`: PDF или DOCX, multipart)."""

    template_id = serializers.IntegerField(required=False, allow_null=True)
    language = serializers.ChoiceField(choices=["ru", "en", "uz"], required=False)
    deviation_text = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    contract_number = serializers.CharField(required=False, allow_blank=True, max_length=64)
    contract_date = serializers.DateField(required=False, allow_null=True)
    file = serializers.FileField(required=False, help_text="Свой файл договора: PDF или DOCX, до 20 МБ.")


class DeskPartnerContractDecisionIn(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "return"])
    confirm_self = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Подтверждение самостоятельного решения единственным держателем «Права».",
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class DeskPartnerApplicationRejectIn(serializers.Serializer):
    rejected_reason = serializers.CharField(
        required=True,
        min_length=1,
        max_length=1000,
        help_text="Причина отклонения заявки.",
    )


class DeskBankChange(serializers.Serializer):
    id = serializers.IntegerField()
    company_id = serializers.IntegerField()
    company_name = serializers.CharField()
    company_inn = serializers.CharField(allow_blank=True)
    company_phone = serializers.CharField(allow_blank=True)
    company_archived = serializers.BooleanField()
    status = serializers.CharField(help_text="pending, approved или rejected.")
    stale = serializers.BooleanField(help_text="Реквизиты изменились после подачи: подтвердить нельзя.")
    old_bank_details = serializers.CharField(allow_blank=True, help_text="Без права подтверждать — маска.")
    new_bank_details = serializers.CharField(allow_blank=True, help_text="Без права подтверждать — маска.")
    requested_by_name = serializers.CharField()
    requested_by_email = serializers.CharField(allow_blank=True)
    requested_ip = serializers.IPAddressField(allow_null=True)
    created_at = serializers.DateTimeField()
    decided_at = serializers.DateTimeField(allow_null=True)
    decided_by_name = serializers.CharField(allow_null=True)
    reject_reason = serializers.CharField(allow_null=True)


class DeskBankChangeListResponse(serializers.Serializer):
    items = DeskBankChange(many=True)
    pending_count = serializers.IntegerField()


class DeskBankChangeRejectIn(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class DeskPerson(serializers.Serializer):
    """Человек контрагента для «Люди» Платформы (FR-11)."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    position = serializers.CharField(allow_null=True)
    has_email = serializers.BooleanField(help_text="Есть почта — открывается по одному человеку (`retrieve`)")
    has_phone = serializers.BooleanField(help_text="Есть телефон — открывается по одному человеку (`retrieve`)")
    is_primary = serializers.BooleanField()
    company = DeskRef()
    kind = serializers.ChoiceField(choices=["client", "partner"])
    photo_version = serializers.CharField(
        allow_null=True,
        help_text="Версия фото контакта (отпечаток файла); `null` — фото нет. Адреса хранилища не отдаются",
    )


class DeskPeoplePage(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = DeskPerson(many=True)


class DeskCounterpartyRoles(serializers.Serializer):
    client = serializers.BooleanField(help_text="Клиент — книга продавца (заводит CRM)")
    supplier = serializers.BooleanField(help_text="Поставщик — отметка или действующие предложения")
    manufacturer = serializers.BooleanField(help_text="Изготовитель — отметка; у брендов ссылка на компанию")
    partner = serializers.BooleanField(help_text="Партнёр с кабинетом — отношение `partner` приглашено или активно")
    organization = serializers.BooleanField(help_text="Организация — адресат писем без сделок (тип `ORGANIZATION`)")


class DeskOrganization(serializers.Serializer):
    """Организация-контрагент для поля «Организация» письма (пункт «Ш»)."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    inn = serializers.CharField(allow_null=True)
    email = serializers.CharField(allow_null=True, help_text="Общая почта организации (`Company.email`)")
    contact_person = serializers.CharField(allow_null=True, help_text="Контактное лицо — для строки «Кому»")
    kind = serializers.ChoiceField(choices=["client", "partner"])
    roles = DeskCounterpartyRoles(help_text="Роли компании — отметки, как в карточке контрагента")
    country = serializers.CharField(allow_null=True, help_text="Название страны компании")
    crm_client_id = serializers.IntegerField(allow_null=True, help_text="Клиент CRM, с которым связана компания")
    logo_version = serializers.CharField(
        allow_null=True,
        help_text="Версия логотипа (отпечаток файла); `null` — логотипа нет. Адреса хранилища не отдаются",
    )


class DeskOrganizationPage(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = DeskOrganization(many=True)


class DeskCounterpartyPerson(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    position = serializers.CharField(allow_null=True)
    is_primary = serializers.BooleanField(help_text="Главный контакт — отдельного поля «контактное лицо» нет")
    has_cabinet = serializers.BooleanField(help_text="Входит в кабинет")
    has_phone = serializers.BooleanField()
    has_email = serializers.BooleanField()
    photo_version = serializers.CharField(allow_null=True, help_text="Версия фото контакта; `null` — фото нет")


class DeskCounterpartyAccount(serializers.Serializer):
    id = serializers.IntegerField()
    currency = serializers.CharField(allow_null=True)
    bank_name = serializers.CharField(allow_blank=True)
    bank_country = serializers.CharField(allow_null=True, help_text="Код страны банка ISO 3166-1")
    account = serializers.CharField(help_text="Номер группами по 4 знака или последние 4 знака (`accounts_masked`)")
    mfo = serializers.CharField(allow_blank=True)
    swift = serializers.CharField(allow_blank=True)
    is_default = serializers.BooleanField(help_text="Основной в своей валюте")


class DeskDoNotWorkIn(serializers.Serializer):
    reason = serializers.CharField(
        max_length=1000, allow_blank=True, help_text="Причина — обязательный текст (пустая — 400 `REASON_REQUIRED`)"
    )
    until = serializers.DateField(required=False, allow_null=True, help_text="Необязательная дата окончания")


class DeskCounterparty(serializers.Serializer):
    """Карточка контрагента — одна компания во всех ролях (ADR-0028, СУЩ-2.5)."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    inn = serializers.CharField(allow_null=True)
    registration_number = serializers.CharField(allow_null=True)
    country = serializers.CharField(allow_null=True)
    legal_address = serializers.CharField(allow_null=True)
    crm_client_id = serializers.IntegerField(allow_null=True, help_text="Клиент CRM, с которым связана компания")
    logo_version = serializers.CharField(allow_null=True, help_text="Версия логотипа; `null` — логотипа нет")
    roles = DeskCounterpartyRoles()
    people = DeskCounterpartyPerson(many=True)
    bank_accounts = DeskCounterpartyAccount(many=True)
    accounts_masked = serializers.BooleanField(help_text="Номера счетов скрыты: нет `finance.view`")
    brands = DeskRef(many=True, help_text="Бренды, которые выпускает компания (справочник «Бренды»)")
    do_not_work = DoNotWorkFacts(
        allow_null=True,
        help_text="Отметка «Не работать» (Х-8): причина, кто и когда поставил, срок; `null` — с компанией работаем",
    )


class DeskOrganizationIn(serializers.Serializer):
    """Новая организация-адресат из письма (СУЩ-2.6)."""

    name = serializers.CharField(max_length=255)
    tin = serializers.CharField(max_length=14, required=False, allow_blank=True, allow_null=True)
    registration_number = serializers.CharField(max_length=64, required=False, allow_blank=True)
    country_id = serializers.IntegerField(required=False, allow_null=True)
    legal_address = serializers.CharField(max_length=500, required=False, allow_blank=True)
    role = serializers.CharField(
        max_length=20,
        required=False,
        help_text=(
            "Роль новой компании: `organization` (по умолчанию), `supplier` или `manufacturer` — последние два "
            "требуют права `supply.manage`"
        ),
    )


class DeskCounterpartyRequisitesIn(serializers.Serializer):
    """Правка реквизитов контрагента (СУЩ-2.7): только переданные поля."""

    name = serializers.CharField(max_length=255, required=False)
    tin = serializers.CharField(max_length=14, required=False, allow_blank=True, allow_null=True)
    registration_number = serializers.CharField(max_length=64, required=False, allow_blank=True, allow_null=True)
    country_id = serializers.IntegerField(required=False, allow_null=True)
    legal_address = serializers.CharField(max_length=1000, required=False, allow_blank=True, allow_null=True)


class DeskCounterpartyRoleIn(serializers.Serializer):
    role = serializers.ChoiceField(choices=["supplier", "manufacturer"])
    on = serializers.BooleanField()


class DeskOrganizationPerson(serializers.Serializer):
    """Человек организации для поля выбора: должность и почта (телефон — только через `parties/people`)."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    position = serializers.CharField(allow_null=True)
    email = serializers.CharField(allow_null=True)
    is_primary = serializers.BooleanField()
    photo_version = serializers.CharField(allow_null=True, help_text="Версия фото контакта; `null` — фото нет")


class DeskOrganizationPeople(serializers.Serializer):
    results = DeskOrganizationPerson(many=True)


class DeskPersonContacts(serializers.Serializer):
    """Телефон и почта одного человека контрагента (FR-11): Платформа открывает по нажатию и пишет показ в журнал."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    phone = serializers.CharField(allow_null=True)
    email = serializers.CharField(allow_null=True)


class DeskPictureIn(serializers.Serializer):
    """Загрузка логотипа или фото (ЕД-5, СУЩ-3): квадрат, уже обрезанный клиентом."""

    file = serializers.FileField(help_text="JPEG, PNG или WebP до 2 МБ; сервер перекодирует в квадрат 256×256 WebP")


class DeskCounterpartyLogos(serializers.Serializer):
    """Версии логотипов нескольких компаний одним ответом — для строк списков, где сама компания приходит из CRM."""

    results = serializers.DictField(
        child=serializers.CharField(allow_null=True), help_text="`{id компании: версия логотипа или null}`"
    )


class DeskPersonPhoto(serializers.Serializer):
    id = serializers.IntegerField()
    photo_version = serializers.CharField(allow_null=True, help_text="Новая версия фото; `null` — фото убрано")
