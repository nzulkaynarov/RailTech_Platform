"""Схемы проектов (D2-5, SPEC-v3 §7.3): список и карточка «Все проекты» и входные тела действий по договору и акту.

Ответы собирает `crm/services/projects.py` словарями; здесь — явные схемы для OpenAPI (drf-spectacular) и проверка
формы ответа. Слова статусов — SPEC-v3 §2.4 (а не коды ERP): договор — `contract_flow.V3_STATUS`, счёт — `invoice_word`,
акт — `act_word`.
"""

from parties.do_not_work import DoNotWorkFacts
from rest_framework import serializers

from core.quantity import QuantityField
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
#: ДП-1: «Отметить: подписан» заметкой — отдельный список: у прежних действий схема не меняется (новое значение enum ломает ответ).
CONTRACT_SIGNING_ACTIONS = ["mark_signed"]
#: ДОК-10: действия договора по шаблону, доступные сейчас (отдельный список — у прежних действий схема не меняется).
CONTRACT_TEMPLATE_ACTIONS = ["sign_ours", "request_deviation", "decide_deviation"]
ACT_ACTIONS = ["attach_scan", "return", "reissue"]
ACT_BLOCKERS = ["no_invoice", "act_exists", "forbidden"]
JOURNAL_DOCUMENTS = ["contract", "act", "invoice", "quote", "project"]


class ProjectMoneySerializer(serializers.Serializer):
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
    send_blocker_code = serializers.CharField(
        allow_null=True,
        required=False,
        help_text=(
            "Х-1: пока проект не ушёл клиенту — код причины, по которой его нельзя отправить (визы маршрута подписи); "
            "`null` — ничего не мешает (визы Х-1 и правила шаблона ДОК-10 — одна проверка). Открытое множество кодов: "
            "см. `send_blocker.code`. Слова и роли — `send_blocker` карточки"
        ),
    )


class InvoiceRefSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Последний не отменённый счёт проекта")
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=INVOICE_WORDS)
    count = serializers.IntegerField(help_text="Сколько не отменённых счетов у проекта")


class ActRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=ACT_WORDS)
    has_scan = serializers.BooleanField(
        help_text="Файл подписанного акта приложен; при `signed` без файла акт принят клиентом в кабинете"
    )


class ProjectDocumentsSerializer(serializers.Serializer):
    quote = QuoteRefSerializer(allow_null=True)
    contract = ContractRefSerializer(allow_null=True)
    invoice = InvoiceRefSerializer(allow_null=True)
    act = ActRefSerializer(allow_null=True)


class ProjectRowSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField(help_text="Сделка ERP")
    number = serializers.CharField(
        help_text="Номер сделки (`Deal.number`), без номера — `D-<id>`; BFF его не составляет"
    )
    title = serializers.CharField(allow_blank=True)
    company_id = serializers.IntegerField(allow_null=True)
    company_name = serializers.CharField(allow_blank=True)
    is_test = serializers.BooleanField(
        required=False, help_text="ТЕСТ-2: проект тестовой компании; приходит только при `?test=all`"
    )
    created_at = serializers.DateTimeField()
    step = serializers.ChoiceField(choices=STEPS)
    client_status = serializers.ChoiceField(choices=CLIENT_STATUSES, help_text="Ключ `client-statuses.yaml`")
    total = ProjectMoneySerializer(allow_null=True, help_text="Сумма последнего КП, видимого клиенту, с НДС")
    manager = PersonSerializer(allow_null=True)
    responsible = PersonSerializer(allow_null=True, help_text="Кто ведёт: взявший в работу, иначе менеджер")
    due_date = serializers.DateField(allow_null=True)
    documents = ProjectDocumentsSerializer()
    problems = serializers.ListField(child=serializers.ChoiceField(choices=PROBLEMS))
    act_blocker = serializers.ChoiceField(
        choices=ACT_BLOCKERS,
        allow_null=True,
        help_text="Почему акт выпустить нельзя: нет счёта, акт уже есть, нет права `fulfillment.act`; `null` — можно",
    )
    act_needs_delivery = serializers.BooleanField(
        required=False,
        help_text=(
            "Акт иначе можно выпустить, но товар ещё не доставлен: акт — после доставки или приёмки клиентом (СЦ-9). "
            "Выпуск раньше — 409 `ACT_NOT_DELIVERED`"
        ),
    )


class ProjectPageSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Сколько проектов подошло под фильтры")
    results = ProjectRowSerializer(many=True)


class OnBehalfNoteSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=["phone", "email", "messenger", "in_person", "paper"])
    counterparty_person = serializers.CharField()


class ProjectJournalEntrySerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    code = serializers.CharField(help_text="Код события журнала (`contract.scan_attached`, …); пусто у прежних записей")
    text = serializers.CharField(help_text="Фраза на русском: запасной текст, если у кода нет перевода")
    actor_name = serializers.CharField(allow_null=True)
    document = serializers.ChoiceField(choices=JOURNAL_DOCUMENTS, allow_null=True)
    number = serializers.CharField(allow_null=True)
    reason = serializers.CharField(allow_blank=True, help_text="Причина или заметка к действию")
    on_behalf = OnBehalfNoteSerializer(
        allow_null=True,
        required=False,
        help_text="Действие контрагента записал сотрудник (A1, A2 волны 18a): канал и лицо со стороны клиента",
    )


class QuoteCardSerializer(QuoteRefSerializer):
    outgoing_number = serializers.CharField(allow_blank=True)
    valid_until = serializers.DateField(allow_null=True)


class ContractTemplateCardSerializer(serializers.Serializer):
    """Договор по шаблону (ДОК-10): имя и редакция, отступление, путь по фактам. Пусто у договоров прежним путём."""

    id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    edition = serializers.IntegerField()
    deviation = serializers.ChoiceField(
        choices=["none", "requested", "approved", "rejected"], help_text="Отступление от шаблона: из фактов договора"
    )
    deviation_text = serializers.CharField(allow_blank=True)
    visas_required = serializers.BooleanField(help_text="Договор идёт по маршруту виз (Х-1) — только с отступлением")
    steps = serializers.ListField(
        child=serializers.DictField(), help_text="Путь: assembled, our_signature, in_cabinet, signed_both"
    )
    actions = serializers.ListField(
        child=serializers.ChoiceField(choices=CONTRACT_TEMPLATE_ACTIONS),
        help_text="Что можно сделать СЕЙЧАС этому сотруднику с договором по шаблону",
    )


class ContractTermCardSerializer(serializers.Serializer):
    """Срок подписанного договора (ДС-1): считается при подписании из правила компании и шаблона; вручную не вводится."""

    state = serializers.CharField(
        help_text="open — без срока; renews — продлится сам; ends — закончится (отказ или продление соглашением); expired — срок вышел",
    )
    rule = serializers.CharField(help_text="calendar_year / twelve_months / open")
    renewal = serializers.CharField(help_text="auto / by_agreement / none")
    valid_from = serializers.DateField()
    valid_until = serializers.DateField(allow_null=True)
    last_notice_date = serializers.DateField(allow_null=True, help_text="Последний день отказа от продления")
    notice_days = serializers.IntegerField()
    renewals_count = serializers.IntegerField()
    foreign = serializers.BooleanField(help_text="Иностранный контрагент: продление — соглашением, не автоматом")
    declined_by = serializers.CharField(allow_null=True, help_text="company / client; null — отказа нет")
    declined_at = serializers.DateTimeField(allow_null=True)
    template_edition = serializers.IntegerField(
        allow_null=True, help_text="Редакция шаблона, на которой подписан договор"
    )
    newer_edition = serializers.IntegerField(
        allow_null=True, help_text="Есть более новая утверждённая редакция шаблона"
    )
    confidentiality_years = serializers.IntegerField(
        allow_null=True, help_text="NDA: лет тайны после окончания (справка)"
    )
    trade_secret_indefinite = serializers.BooleanField(help_text="NDA: коммерческая тайна — без срока (справка)")
    actions = serializers.ListField(
        child=serializers.ChoiceField(choices=["decline_renewal", "restore_renewal", "renew", "send_new_edition"]),
        help_text="Что можно сделать СЕЙЧАС этому сотруднику со сроком договора",
    )


class ContractSendBlockerSerializer(serializers.Serializer):
    """Почему проект договора нельзя отправить клиенту: визы Х-1 (ADR-0025), отступление или наша подпись (ДОК-10)."""

    code = serializers.CharField(
        help_text=(
            "Открытое множество (новые причины добавляются без смены контракта): "
            "visas_not_requested — договор ещё не на визах; visas_declined — EDS не принял договор на визы (причина в remark); visas_pending — не все визы поставлены; visas_returned — "
            "виза возвращена с замечанием; no_visa_holder — в компании нет держателя нужного права; "
            "CONTRACT_DEVIATION_PENDING — отступление от шаблона ждёт решения; CONTRACT_NEEDS_OUR_SIGNATURE — нужна "
            "наша подпись до отправки (ДОК-10)"
        ),
    )
    message = serializers.CharField(help_text="Причина словами для сотрудника («Нужны визы: бухгалтер, юрист»)")
    missing = serializers.ListField(
        child=serializers.CharField(), help_text="Роли, чьих виз не хватает, словами в нижнем регистре"
    )
    missing_permissions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Те же визы кодами прав маршрута (`approvals.visa_finance`): Платформа переводит их на язык сотрудника",
    )
    remark = serializers.CharField(
        allow_blank=True, help_text="Замечание визирующего или причина отказа EDS, как написаны; пусто — нет"
    )
    settings_link = serializers.BooleanField(
        help_text="Нужной роли нет ни у одного сотрудника: назначить её можно в настройках (ссылка без тупика)"
    )


class ContractConflictSerializer(serializers.Serializer):
    """Тело 409 действий по договору и акту: код; при `CONTRACT_VISAS_REQUIRED` (Х-1) ещё причина словами и роли без визы."""

    detail = serializers.CharField(help_text="Код отказа")
    reason = serializers.CharField(required=False, help_text="Причина словами («Нужны визы: бухгалтер, юрист»)")
    missing = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Роли без визы словами в нижнем регистре"
    )


class RemarkSegmentSerializer(serializers.Serializer):
    op = serializers.ChoiceField(choices=["equal", "del", "ins"])
    text = serializers.CharField(allow_blank=True)


class RemarkItemSerializer(serializers.Serializer):
    point = serializers.CharField(allow_blank=True, help_text="Номер пункта; пусто — у абзаца номера нет")
    kind = serializers.ChoiceField(choices=["changed", "added", "removed"])
    ours = serializers.CharField(allow_blank=True)
    theirs = serializers.CharField(allow_blank=True)
    segments = RemarkSegmentSerializer(many=True)


class RemarkSummarySerializer(serializers.Serializer):
    changed = serializers.ListField(child=serializers.CharField())
    added = serializers.ListField(child=serializers.CharField())
    removed = serializers.ListField(child=serializers.CharField())
    total = serializers.IntegerField()
    more = serializers.IntegerField(
        required=False, help_text="Сколько пунктов не поместилось в списки выше (предел 30 на вид)"
    )
    comparable = serializers.BooleanField(
        help_text="Редакция контрагента сравнена с нашей (DOCX); XLSX и без файла — нет"
    )


class RemarkVoteCardSerializer(serializers.Serializer):
    user = PersonSerializer()
    agree = serializers.BooleanField()
    comment = serializers.CharField(allow_blank=True)
    at = serializers.DateTimeField()


class RemarkCardSerializer(serializers.Serializer):
    """ДП-1: замечания контрагента на согласовании: комментарий, файл, что изменилось, ответы и что можно этому сотруднику."""

    id = serializers.IntegerField()
    edition = serializers.IntegerField()
    received_at = serializers.DateTimeField()
    author_name = serializers.CharField(allow_blank=True)
    comment = serializers.CharField()
    file_name = serializers.CharField(allow_blank=True)
    has_file = serializers.BooleanField()
    summary = RemarkSummarySerializer()
    items = RemarkItemSerializer(many=True)
    votes = RemarkVoteCardSerializer(many=True)
    awaiting = PersonSerializer(many=True, help_text="Кто ещё не ответил")
    deciders = PersonSerializer(many=True, help_text="При разногласии решает: держатели права подписи")
    dispute = serializers.BooleanField(help_text="Есть ответ «Не согласен» и все ответили: решение за директором")
    actions = serializers.ListField(
        child=serializers.ChoiceField(choices=["vote", "decide"]), help_text="Что можно этому сотруднику сейчас"
    )


class ContractCardSerializer(ContractRefSerializer):
    template = ContractTemplateCardSerializer(allow_null=True)
    term = ContractTermCardSerializer(allow_null=True, required=False, help_text="Срок: только у подписанного договора")
    total = ProjectMoneySerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    client_agreed_at = serializers.DateTimeField(allow_null=True)
    signed_at = serializers.DateTimeField(allow_null=True)
    has_pdf = serializers.BooleanField()
    has_scan = serializers.BooleanField()
    actions = serializers.ListField(
        child=serializers.ChoiceField(choices=CONTRACT_ACTIONS),
        help_text="Что можно сделать СЕЙЧАС этому сотруднику: допустимо из статуса и разрешено правами роли",
    )
    signing_actions = serializers.ListField(
        child=serializers.ChoiceField(choices=CONTRACT_SIGNING_ACTIONS),
        required=False,
        help_text="ДП-1: `mark_signed` — «Отметить: подписан» заметкой, пока договор ожидает подписания и право `contract.sign` есть",
    )
    send_blocker = ContractSendBlockerSerializer(
        allow_null=True,
        required=False,
        help_text="Х-1: пока проект не ушёл клиенту — что мешает его отправить; `null` — ничего (действие `send_to_client` в `actions`)",
    )
    remark = RemarkCardSerializer(
        allow_null=True, required=False, help_text="ДП-1: замечания контрагента на согласовании; `null` — их нет"
    )
    history = ProjectJournalEntrySerializer(many=True)


class InvoiceCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=INVOICE_WORDS)
    total = ProjectMoneySerializer(allow_null=True)
    paid = ProjectMoneySerializer(allow_null=True)
    balance_due = ProjectMoneySerializer(allow_null=True)
    issued_at = serializers.DateField(allow_null=True)
    due_date = serializers.DateField(allow_null=True)
    has_pdf = serializers.BooleanField()


class ActCardSerializer(ActRefSerializer):
    total = ProjectMoneySerializer(allow_null=True)
    issued_at = serializers.DateField(allow_null=True)
    signed_at = serializers.DateTimeField(allow_null=True)
    rejection_reason = serializers.CharField(allow_blank=True)
    has_pdf = serializers.BooleanField()
    actions = serializers.ListField(child=serializers.ChoiceField(choices=ACT_ACTIONS))
    history = ProjectJournalEntrySerializer(many=True)


class FulfillmentCardSerializer(serializers.Serializer):
    status = serializers.CharField(allow_null=True)
    status_name = serializers.CharField(allow_null=True)
    expected_delivery_date = serializers.DateField(allow_null=True)
    shipped_at = serializers.DateTimeField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)
    accepted_at = serializers.DateTimeField(allow_null=True)
    tracking_number = serializers.CharField(allow_blank=True, help_text="№ накладной перевозчика или трек")
    carrier = serializers.CharField(allow_blank=True)
    actions = serializers.ListField(
        child=serializers.ChoiceField(choices=["in_transit", "delivered"]),
        help_text="Отметки доставки, доступные этому сотруднику сейчас (статус исполнения и право `fulfillment.manage`)",
    )
    goods_not_shipped = serializers.BooleanField(
        help_text="Товар с карточкой каталога ещё не отгружен со склада: отметки доставки не предлагаются (`actions` пуст)"
    )
    proof_attachment_id = serializers.IntegerField(
        allow_null=True, help_text="Вложение подтверждения доставки (`/sourcing/attachments/{id}/download/`)"
    )
    proof_name = serializers.CharField(allow_null=True, help_text="Имя файла подтверждения доставки")


class DeliveryMarkInSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["in_transit", "delivered"], help_text="`in_transit` — отправлено, в пути; `delivered` — доставлено"
    )
    on_date = serializers.DateField(help_text="Дата отправки или доставки; не позже сегодня и не раньше отправки")
    waybill = serializers.CharField(
        required=False, allow_blank=True, max_length=128, help_text="№ накладной перевозчика"
    )
    file = serializers.FileField(required=False, help_text="Подтверждение доставки: накладная, фото, PDF (до 20 МБ)")


class DeliveryLineCardSerializer(serializers.Serializer):
    line_no = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    quantity = QuantityField(allow_null=True)
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
    fulfillment = FulfillmentCardSerializer(allow_null=True)
    delivery_lines = DeliveryLineCardSerializer(many=True)
    journal = ProjectJournalEntrySerializer(many=True)
    do_not_work = DoNotWorkFacts(
        allow_null=True,
        help_text="Х-8: у компании проекта отметка «Не работать» — полоса в карточке; документы в работе не отменяются",
    )


class ContractTransitionInSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, help_text="Обязательна для `reject`")
    note = serializers.CharField(required=False, allow_blank=True, help_text="Заметка в журнал (оператор ЭДО, ссылка)")
    # A2 волны 18a: согласие клиента записывает сотрудник — как клиент сообщил и кто со стороны клиента.
    channel = serializers.ChoiceField(
        choices=["phone", "email", "messenger", "in_person", "paper"],
        required=False,
        help_text="Обязателен для `client-agreed`: как клиент сообщил согласие",
    )
    counterparty_person = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="Обязателен для `client-agreed`: кто со стороны клиента",
    )


class ContractRemarkVoteInSerializer(serializers.Serializer):
    agree = serializers.BooleanField(help_text="`true` — «Согласен», `false` — «Не согласен»")
    comment = serializers.CharField(required=False, allow_blank=True, help_text="Обязателен при «Не согласен»")


class ContractRemarkDecideInSerializer(serializers.Serializer):
    accept = serializers.BooleanField(help_text="`true` — принять редакцию контрагента, `false` — ответить своей")
    text = serializers.CharField(
        required=False, allow_blank=True, help_text="Ответ контрагенту; обязателен при `accept=false`"
    )


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
