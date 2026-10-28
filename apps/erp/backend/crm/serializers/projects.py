"""Схемы проектов (D2-5, SPEC-v3 §7.3): список и карточка «Все проекты» и входные тела действий по договору и акту.

Ответы собирает `crm/services/projects.py` словарями; здесь — явные схемы для OpenAPI (drf-spectacular) и проверка
формы ответа. Слова статусов — SPEC-v3 §2.4 (а не коды ERP): договор — `contract_flow.V3_STATUS`, счёт — `invoice_word`,
акт — `act_word`.
"""

from rest_framework import serializers

from crm.serializers.billing import ActSerializer, ContractSerializer

CONTRACT_WORDS = ["project", "client_agreed", "issued_at_operator", "signed", "rejected", "cancelled"]
INVOICE_WORDS = ["to_issue", "issued", "partial", "paid", "overdue", "cancelled"]
ACT_WORDS = ["project", "returned", "issued", "signed", "cancelled"]
STEPS = ["CONTRACT", "PAYMENT", "DONE"]
CLIENT_STATUSES = [
    "contract_review",
    "contract_signing",
    "awaiting_payment",
    "fulfilling",
    "awaiting_acceptance",
    "done",
]
PROBLEMS = ["no_contract", "contract_rejected", "act_returned", "invoice_overdue"]
CONTRACT_ACTIONS = ["send_to_client", "client_agreed", "reject", "revise", "mark_issued", "attach_scan"]
ACT_ACTIONS = ["attach_scan", "return", "reissue"]
ACT_BLOCKERS = ["no_invoice", "act_exists", "forbidden"]
JOURNAL_DOCUMENTS = ["contract", "act", "invoice", "quote", "project"]


class MoneySerializer(serializers.Serializer):
    amount = serializers.CharField(help_text="Сумма строкой с двумя знаками, `-?\\d+\\.\\d{2}`")
    currency = serializers.CharField(help_text="Код валюты, три заглавные буквы")


class PersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class QuoteRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField(allow_blank=True)
    status = serializers.CharField(help_text="Всегда `accepted`: КП проекта принято клиентом")
    version = serializers.IntegerField()


class ContractRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=CONTRACT_WORDS)
    sent_to_client = serializers.BooleanField(help_text="Проект ушёл клиенту на согласование и виден ему в портале")


class InvoiceRefSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Последний не отменённый счёт проекта")
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=INVOICE_WORDS)
    count = serializers.IntegerField(help_text="Сколько не отменённых счетов у проекта")


class ActRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=ACT_WORDS)


class ProjectDocumentsSerializer(serializers.Serializer):
    quote = QuoteRefSerializer(allow_null=True)
    contract = ContractRefSerializer(allow_null=True)
    invoice = InvoiceRefSerializer(allow_null=True)
    act = ActRefSerializer(allow_null=True)


class ProjectRowSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField(help_text="Сделка ERP; номер ПР-ГГГГ-NNN составляет BFF (B-010)")
    title = serializers.CharField(allow_blank=True)
    company_id = serializers.IntegerField(allow_null=True)
    company_name = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    step = serializers.ChoiceField(choices=STEPS)
    client_status = serializers.ChoiceField(choices=CLIENT_STATUSES, help_text="Ключ `client-statuses.yaml`")
    total = MoneySerializer(allow_null=True, help_text="Сумма последнего КП, видимого клиенту, с НДС")
    manager = PersonSerializer(allow_null=True)
    responsible = PersonSerializer(allow_null=True, help_text="Кто ведёт: взявший в работу, иначе менеджер")
    due_date = serializers.DateField(allow_null=True)
    documents = ProjectDocumentsSerializer()
    problems = serializers.ListField(child=serializers.ChoiceField(choices=PROBLEMS))


class ProjectPageSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Сколько проектов подошло под фильтры")
    results = ProjectRowSerializer(many=True)


class ProjectJournalEntrySerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    code = serializers.CharField(help_text="Код события журнала (`contract.scan_attached`, …); пусто у прежних записей")
    text = serializers.CharField(help_text="Фраза на русском: запасной текст, если у кода нет перевода")
    actor_name = serializers.CharField(allow_null=True)
    document = serializers.ChoiceField(choices=JOURNAL_DOCUMENTS, allow_null=True)
    number = serializers.CharField(allow_null=True)
    reason = serializers.CharField(allow_blank=True, help_text="Причина или заметка к действию")


class QuoteCardSerializer(QuoteRefSerializer):
    outgoing_number = serializers.CharField(allow_blank=True)
    valid_until = serializers.DateField(allow_null=True)


class ContractCardSerializer(ContractRefSerializer):
    total = MoneySerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    client_agreed_at = serializers.DateTimeField(allow_null=True)
    signed_at = serializers.DateTimeField(allow_null=True)
    has_pdf = serializers.BooleanField()
    has_scan = serializers.BooleanField()
    actions = serializers.ListField(
        child=serializers.ChoiceField(choices=CONTRACT_ACTIONS),
        help_text="Что можно сделать СЕЙЧАС этому сотруднику: допустимо из статуса и разрешено правами роли",
    )
    history = ProjectJournalEntrySerializer(many=True)


class InvoiceCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=INVOICE_WORDS)
    total = MoneySerializer(allow_null=True)
    paid = MoneySerializer(allow_null=True)
    balance_due = MoneySerializer(allow_null=True)
    issued_at = serializers.DateField(allow_null=True)
    due_date = serializers.DateField(allow_null=True)
    has_pdf = serializers.BooleanField()


class ActCardSerializer(ActRefSerializer):
    total = MoneySerializer(allow_null=True)
    issued_at = serializers.DateField(allow_null=True)
    signed_at = serializers.DateTimeField(allow_null=True)
    rejection_reason = serializers.CharField(allow_blank=True)
    has_pdf = serializers.BooleanField()
    has_scan = serializers.BooleanField()
    actions = serializers.ListField(child=serializers.ChoiceField(choices=ACT_ACTIONS))
    history = ProjectJournalEntrySerializer(many=True)


class FulfillmentCardSerializer(serializers.Serializer):
    status = serializers.CharField(allow_null=True)
    status_name = serializers.CharField(allow_null=True)
    expected_delivery_date = serializers.DateField(allow_null=True)
    shipped_at = serializers.DateTimeField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)
    accepted_at = serializers.DateTimeField(allow_null=True)
    tracking_number = serializers.CharField(allow_blank=True)
    carrier = serializers.CharField(allow_blank=True)


class DeliveryLineCardSerializer(serializers.Serializer):
    line_no = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    quantity = serializers.IntegerField(allow_null=True)
    unit = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    eta = serializers.DateField(allow_null=True)
    shipped_at = serializers.DateTimeField(allow_null=True)
    tracking = serializers.CharField(allow_blank=True)


class ProjectCardSerializer(ProjectRowSerializer):
    quote = QuoteCardSerializer(allow_null=True)
    contract = ContractCardSerializer(allow_null=True)
    can_create_contract = serializers.BooleanField(
        help_text="КП принято, договора нет, и у сотрудника есть право `contract.manage`: можно сформировать проект"
    )
    invoices = InvoiceCardSerializer(many=True)
    act = ActCardSerializer(allow_null=True)
    act_blocker = serializers.ChoiceField(
        choices=ACT_BLOCKERS,
        allow_null=True,
        help_text="Почему акт сейчас выпустить нельзя: нет счёта, акт уже есть, нет права `fulfillment.act`",
    )
    fulfillment = FulfillmentCardSerializer(allow_null=True)
    delivery_lines = DeliveryLineCardSerializer(many=True)
    journal = ProjectJournalEntrySerializer(many=True)


class ContractTransitionInSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, help_text="Обязательна для `reject`")
    note = serializers.CharField(required=False, allow_blank=True, help_text="Заметка в журнал (оператор ЭДО, ссылка)")


class ContractScanInSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Скан подписанного договора: PDF, jpg, png или webp до 20 МБ")
    note = serializers.CharField(required=False, allow_blank=True)


class ActScanInSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Скан подписанного акта: PDF, jpg, png или webp до 20 МБ")


class ActReturnInSerializer(serializers.Serializer):
    reason = serializers.CharField(help_text="Причина возврата акта заказчиком — обязательна")


class ContractFlowSerializer(ContractSerializer):
    """Ответ действий по договору (D2-5): тот же договор, но имена подписантов честно могут быть пустыми — подпись
    вне платформы, подписантов ERP может не знать. Отдельный компонент: у прежних операций схема не меняется."""

    client_signer_name = serializers.CharField(
        source="client_signer.get_full_name", read_only=True, default=None, allow_null=True
    )
    manager_signer_name = serializers.CharField(
        source="manager_signer.get_full_name", read_only=True, default=None, allow_null=True
    )


class ActFlowSerializer(ActSerializer):
    """Ответ действий по акту (D2-5): подписанты акта могут быть неизвестны (скан, возврат)."""

    issuer_signer_name = serializers.CharField(
        source="issuer_signer.get_full_name", read_only=True, default=None, allow_null=True
    )
    acceptor_signer_name = serializers.CharField(
        source="acceptor_signer.get_full_name", read_only=True, default=None, allow_null=True
    )
