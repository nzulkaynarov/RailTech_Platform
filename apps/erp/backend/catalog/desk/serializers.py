"""Явные схемы запросов и ответов операций D2-3 (CONVENTIONS ERP §5: каждая операция `/api/v1` описана).

Ответы собирают сервисы `catalog.desk.*` словарями; эти классы нужны схеме OpenAPI и входной проверке формы. Имена
компонентов начинаются с `Desk`. Закрытые поля (`price`, `rate`) — `null` у того, кому ERP их не отдаёт.
"""

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from catalog.constants import PriceVisibility
from catalog.desk.items import ALL_KINDS
from catalog.models import Brigade, ProductFieldProposal, SupplierOffer
from catalog.models.reviews import ISSUE_FIELDS, MAX_ISSUE_COMMENT, MAX_ISSUES


class Money(serializers.Serializer):
    amount = serializers.CharField(help_text="Сумма строкой с двумя знаками.")
    currency = serializers.CharField(allow_null=True, help_text="Код валюты ISO 4217.")


class DeskUnit(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class DeskRef(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class DeskReviewInfo(serializers.Serializer):
    """Ожидание решения по карточке партнёра (PART-3): кто прислал, когда и до какого срока ответить."""

    kind = serializers.ChoiceField(
        choices=["card", "changes"],
        help_text="`card` — карточка на проверке; `changes` — предложения партнёра к опубликованной.",
    )
    partner = DeskRef(allow_null=True, help_text="Партнёр: источник данных карточки или приславший предложение.")
    submitted_at = serializers.DateTimeField(help_text="Когда отправлено (старые сверху).")
    due_at = serializers.DateTimeField(help_text="Срок ответа: 24 часа без учёта субботы и воскресенья.")
    overdue = serializers.BooleanField(help_text="Срок прошёл.")


class DeskItemRow(serializers.Serializer):
    id = serializers.IntegerField()
    sku = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(
        choices=list(ALL_KINDS),
        help_text="Тип вычисляется: товар со склада или под заказ, услуга фикс / по этапам / по времени.",
    )
    is_service = serializers.BooleanField()
    unit = DeskUnit(allow_null=True)
    vat_rate = serializers.CharField(allow_null=True, help_text="НДС позиции, %; null — ставка компании по умолчанию.")
    vat_effective = serializers.CharField(
        allow_null=True, help_text="Действующая ставка: своя или компании по умолчанию."
    )
    category = DeskRef(allow_null=True)
    status = serializers.CharField(allow_null=True, help_text="Код статуса карточки: DRAFT, PUBLISHED.")
    offers_count = serializers.IntegerField()
    nearest_valid_until = serializers.DateField(allow_null=True)
    docs_count = serializers.IntegerField()
    proposals_count = serializers.IntegerField(help_text="Изменений от поставщиков на одобрении (CAT-1).")
    review = DeskReviewInfo(
        required=False,
        allow_null=True,
        help_text="Ожидание решения: в списке `review=waiting` и в карточке; null — карточка не ждёт проверки (PART-3).",
    )
    completeness = serializers.IntegerField(
        required=False, help_text="Полнота карточки, % — в списке `review=waiting` и в карточке."
    )


class DeskOfferSupplier(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class DeskOfferProduct(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    sku = serializers.CharField()


class DeskOffer(serializers.Serializer):
    id = serializers.IntegerField()
    supplier = DeskOfferSupplier()
    product = DeskOfferProduct()
    supplier_sku = serializers.CharField()
    price = Money(allow_null=True, help_text="Цена закупки: только с правом на цены поставщиков (иначе null).")
    quota_qty = serializers.IntegerField(help_text="Квота: сколько единиц поставщик готов отгрузить по этой цене.")
    min_order_qty = serializers.IntegerField()
    in_stock_lead_days = serializers.IntegerField()
    order_lead_days = serializers.IntegerField()
    stock_status = serializers.CharField(allow_null=True)
    delivery_basis = serializers.CharField(allow_null=True, help_text="Базис поставки Incoterms (код).")
    lead_time = serializers.CharField(help_text="Срок поставки словами, как в прайсе.")
    source = serializers.ChoiceField(choices=SupplierOffer.Source.values, help_text="Откуда цена.")
    updated_at = serializers.DateTimeField()
    valid_from = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)
    is_active = serializers.BooleanField()
    validity = serializers.ChoiceField(choices=["ok", "expiring", "expired"])


class DeskProposal(serializers.Serializer):
    id = serializers.IntegerField()
    field = serializers.ChoiceField(choices=ProductFieldProposal.Field.values)
    current = serializers.CharField(help_text="Значение в карточке на момент загрузки.")
    proposed = serializers.CharField(help_text="Значение из прайса поставщика.")
    supplier = DeskRef(allow_null=True)
    created_at = serializers.DateTimeField()


class DeskPublishState(serializers.Serializer):
    publishable = serializers.BooleanField()
    missing = serializers.ListField(child=serializers.CharField(), help_text="Коды недостающих полей полноты.")


class DeskTechDocRef(serializers.Serializer):
    """Документ товара в карточке (CAT-CARD-1): вид из справочника, номер, орган, сроки, видимость клиенту."""

    id = serializers.IntegerField()
    title = serializers.CharField()
    kind = serializers.CharField(help_text="Код вида из справочника видов документов.")
    kind_name = serializers.CharField(help_text="Название вида.")
    number = serializers.CharField(help_text="Номер документа (сертификата, декларации…); пусто, если не задан.")
    issued_by = serializers.CharField(help_text="Кем выдан.")
    issued_at = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True, help_text="Действует до; null — бессрочно.")
    is_expired = serializers.BooleanField(help_text="Срок «действует до» прошёл.")
    client_visible = serializers.BooleanField(help_text="Клиент видит документ в кабинете.")
    original_name = serializers.CharField()
    size_bytes = serializers.IntegerField()
    previewable = serializers.BooleanField()
    review_state = serializers.ChoiceField(
        choices=["approved", "pending", "rejected"],
        help_text="Проверка присланного партнёром: pending — ждёт сотрудника, клиенту не виден; у документов сотрудников approved.",
    )
    partner = serializers.CharField(allow_null=True, help_text="Название партнёра, приславшего документ из кабинета.")


class DeskImage(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.CharField(help_text="Путь файла в хранилище ERP (`/media/…`); в браузер его отдаёт только BFF.")
    is_main = serializers.BooleanField()
    sort_order = serializers.IntegerField(help_text="Позиция в галерее с нуля, без пропусков.")
    alt = serializers.CharField(help_text="Подпись фото.")


class DeskImageUpload(serializers.Serializer):
    """multipart/form-data: JPEG, PNG или WebP до 5 МБ."""

    image = serializers.FileField()
    alt_text = serializers.CharField(required=False, allow_blank=True, max_length=255)
    is_main = serializers.BooleanField(required=False, help_text="Сделать главным; первое фото товара главное само.")


class DeskImageIn(serializers.Serializer):
    is_main = serializers.BooleanField(required=False, help_text="Только true: главное меняется назначением другого.")
    sort_order = serializers.IntegerField(required=False, min_value=0, help_text="Новая позиция с нуля.")
    alt_text = serializers.CharField(required=False, allow_blank=True, max_length=255)


class DeskOrigin(serializers.Serializer):
    own = DeskRef(allow_null=True, help_text="Страна, заданная в карточке.")
    effective = DeskRef(allow_null=True, help_text="Показываемая страна: своя, иначе страна бренда.")
    brand = DeskRef(allow_null=True, help_text="Страна бренда карточки (подсказка к пустому полю).")
    source = serializers.ChoiceField(choices=["item", "brand", "none"], help_text="Откуда взята показываемая страна.")


class DeskWarranty(serializers.Serializer):
    months = serializers.IntegerField(allow_null=True, help_text="Срок, заданный в карточке.")
    terms = serializers.CharField(help_text="Условия гарантии.")
    effective_months = serializers.IntegerField(
        allow_null=True, help_text="Показываемый срок: свой, иначе срок компании."
    )
    company_months = serializers.IntegerField(
        allow_null=True, help_text="Срок компании по умолчанию (подсказка к пустому полю)."
    )
    source = serializers.ChoiceField(choices=["item", "company", "none"], help_text="Откуда взят показываемый срок.")


class DeskDocumentKind(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    has_validity = serializers.BooleanField(help_text="У документа этого вида есть срок действия.")
    client_visible_default = serializers.BooleanField(help_text="Новый документ этого вида по умолчанию виден клиенту.")
    sort_order = serializers.IntegerField()


class DeskCatalogPrice(serializers.Serializer):
    """Что покажет каталог клиенту (PART-3): уровень видимости и цена-витрина."""

    visibility = serializers.ChoiceField(
        choices=PriceVisibility.choices, help_text="`cabinet` — цену видно; `on_request` — «по запросу»."
    )
    source = serializers.ChoiceField(
        choices=["item", "partner", "company"],
        help_text="Откуда взята видимость: карточка → договорённость с партнёром → компания.",
    )
    price = Money(allow_null=True, help_text="Цена-витрина клиенту; null — «по запросу» или цена не задана.")


class DeskReturnIssue(serializers.Serializer):
    field = serializers.ChoiceField(choices=list(ISSUE_FIELDS), help_text="Поле карточки, к которому замечание.")
    comment = serializers.CharField(max_length=MAX_ISSUE_COMMENT)


class DeskReturnIn(serializers.Serializer):
    """Возврат карточки партнёру: нужна хотя бы одна причина — общий комментарий или замечание по полю."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000, help_text="Общий комментарий.")
    issues = DeskReturnIssue(many=True, required=False, allow_null=True, max_length=MAX_ISSUES)


class DeskItemDetail(DeskItemRow):
    description = serializers.CharField()
    gost_drawing = serializers.CharField()
    hs_code = serializers.CharField()
    manufacturer_part_number = serializers.CharField()
    brand = serializers.CharField(allow_null=True)
    brand_id = serializers.IntegerField(allow_null=True, help_text="Изготовитель (бренд) — id справочника.")
    source_supplier = DeskRef(allow_null=True, help_text="Карточка заведена по прайсу этого поставщика.")
    offers = DeskOffer(many=True)
    prices_visible = serializers.BooleanField(help_text="Видит ли сотрудник цены поставщиков (иначе price = null).")
    tech_docs = DeskTechDocRef(many=True)
    images = DeskImage(many=True, help_text="Фото по порядку; ровно одно главное, если фото есть.")
    origin = DeskOrigin()
    warranty = DeskWarranty()
    proposals = DeskProposal(many=True, help_text="Изменения от поставщиков на одобрении.")
    publish = DeskPublishState()
    catalog_price = DeskCatalogPrice(help_text="Что покажет каталог клиенту.")


class DeskItemIn(serializers.Serializer):
    """Создание и правка позиции. При правке приходят только изменяемые поля."""

    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    kind = serializers.ChoiceField(required=False, choices=list(ALL_KINDS))
    unit_id = serializers.IntegerField(required=False, allow_null=True)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    vat_rate = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, help_text="Процент 0..100; пусто — по умолчанию компании."
    )
    brand_id = serializers.IntegerField(required=False, allow_null=True, help_text="Изготовитель (бренд).")
    manufacturer_part_number = serializers.CharField(required=False, allow_blank=True, max_length=120)
    hs_code = serializers.CharField(required=False, allow_blank=True, max_length=20, help_text="2–10 цифр.")
    country_of_origin_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Страна происхождения; пусто — страна бренда."
    )
    warranty_months = serializers.IntegerField(
        required=False, allow_null=True, help_text="Гарантия, мес. (0–600); пусто — срок компании по умолчанию."
    )
    warranty_terms = serializers.CharField(required=False, allow_blank=True, help_text="Условия гарантии.")


class DeskSupplierRow(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    tin = serializers.CharField()
    registration_number = serializers.CharField(help_text="Рег. номер нерезидента (без ИНН РУз).")
    country = serializers.CharField(allow_null=True)
    country_id = serializers.IntegerField(allow_null=True)
    currency = serializers.CharField(allow_null=True, help_text="Валюта цен поставщика.")
    is_manufacturer = serializers.BooleanField(help_text="Сам выпускает товар (тип «изготовитель»).")
    offers_count = serializers.IntegerField()
    expired_count = serializers.IntegerField(help_text="Действующих предложений с истёкшим сроком цены.")
    expiring_count = serializers.IntegerField(help_text="Срок цены истекает в ближайшие 14 дней.")
    nearest_valid_until = serializers.DateField(allow_null=True)


class DeskSupplierDetail(DeskSupplierRow):
    contact_person = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.CharField()
    website = serializers.CharField()
    legal_address = serializers.CharField()
    offers = DeskOffer(many=True)
    prices_visible = serializers.BooleanField()
    brands = DeskRef(many=True, help_text="Чьи бренды поставляет: изготовители его действующих цен.")
    manufactured_brands = DeskRef(many=True, help_text="Бренды, изготовитель которых — эта компания.")


class DeskSupplierIn(serializers.Serializer):
    """Поставщик — простая карточка компании (CAT-1): ИНН или рег. номер нерезидента — хотя бы одно."""

    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    country_id = serializers.IntegerField(required=False, allow_null=True)
    tin = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=20)
    registration_number = serializers.CharField(required=False, allow_blank=True, max_length=64)
    currency = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=3)
    contact_person = serializers.CharField(required=False, allow_blank=True, max_length=255)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    email = serializers.EmailField(required=False, allow_blank=True)
    website = serializers.URLField(required=False, allow_blank=True, max_length=255)
    legal_address = serializers.CharField(required=False, allow_blank=True)
    is_manufacturer = serializers.BooleanField(required=False)


class DeskMoneyIn(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()


class DeskOfferIn(serializers.Serializer):
    price = DeskMoneyIn(
        required=False, help_text="Цена закупки; нужно право на цены поставщиков (403 SUPPLIER_PRICES_REQUIRED)."
    )
    quota_qty = serializers.IntegerField(required=False, min_value=0)
    min_order_qty = serializers.IntegerField(required=False, min_value=1)
    in_stock_lead_days = serializers.IntegerField(required=False, min_value=0)
    order_lead_days = serializers.IntegerField(required=False, min_value=0)
    stock_status = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_until = serializers.DateField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    delivery_basis = serializers.CharField(required=False, allow_null=True, allow_blank=True, help_text="Incoterms.")
    lead_time = serializers.CharField(required=False, allow_blank=True, max_length=100)
    supplier_sku = serializers.CharField(required=False, allow_blank=True, max_length=100)
    source = serializers.ChoiceField(required=False, choices=SupplierOffer.Source.values)


class DeskOfferCreateIn(DeskOfferIn):
    product_id = serializers.IntegerField()
    price = DeskMoneyIn(help_text="Цена закупки; нужно право на цены поставщиков (403 SUPPLIER_PRICES_REQUIRED).")


class DeskOfferHistoryRow(serializers.Serializer):
    at = serializers.DateTimeField()
    price = Money(allow_null=True, help_text="Только с правом на цены поставщиков.")
    valid_from = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)
    delivery_basis = serializers.CharField(allow_null=True)
    source = serializers.ChoiceField(choices=SupplierOffer.Source.values)
    by = serializers.CharField(allow_null=True)


class DeskCrewRate(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField(allow_null=True)
    unit = serializers.ChoiceField(choices=Brigade.RateUnit.values)


@extend_schema_serializer(component_name="DeskBrigade")
class DeskBrigadeRow(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=Brigade.Kind.values)
    specialization = serializers.CharField()
    headcount = serializers.IntegerField()
    rate = DeskCrewRate(allow_null=True, help_text="Ставка: держатель зоны услуг или cost_margin; иначе null.")
    rate_visible = serializers.BooleanField()
    note = serializers.CharField()
    is_active = serializers.BooleanField()


class DeskCrewRateIn(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()


class DeskBrigadeIn(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    kind = serializers.ChoiceField(required=False, choices=Brigade.Kind.values)
    specialization = serializers.CharField(required=False, allow_blank=True, max_length=255)
    headcount = serializers.IntegerField(required=False, min_value=1, max_value=500)
    rate = DeskCrewRateIn(required=False, allow_null=True)
    rate_unit = serializers.ChoiceField(required=False, choices=Brigade.RateUnit.values)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    is_active = serializers.BooleanField(required=False)


class DeskTechDocProduct(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    sku = serializers.CharField()


class DeskTechDocDeal(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField(
        help_text="Номер ЗВ/ПР, который выдал ERP (ERP-09); пусто — у сделки номера ещё нет."
    )
    title = serializers.CharField()
    client = serializers.CharField()
    stage_code = serializers.CharField(help_text="Код стадии сделки.")
    created_at = serializers.DateTimeField()


class DeskTechDoc(DeskTechDocRef):
    content_type = serializers.CharField()
    product = DeskTechDocProduct(allow_null=True)
    deal = DeskTechDocDeal(allow_null=True)
    uploaded_by = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


class DeskTechDocPassport(serializers.Serializer):
    """Поля документа, общие для загрузки и правки."""

    kind = serializers.CharField(required=False, help_text="Код вида из справочника (`catalog/document-kinds/`).")
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    number = serializers.CharField(required=False, allow_blank=True, max_length=100)
    issued_by = serializers.CharField(required=False, allow_blank=True, max_length=255)
    issued_at = serializers.DateField(required=False, allow_null=True)
    valid_until = serializers.DateField(required=False, allow_null=True, help_text="Пусто — бессрочно.")
    client_visible = serializers.BooleanField(required=False, help_text="Пусто — по умолчанию вида.")


class DeskTechDocUpload(DeskTechDocPassport):
    """multipart/form-data: файл ≤ 20 МБ (PDF, PNG, JPEG, DOC(X), XLS(X)), хотя бы одна привязка — позиция или заявка."""

    file = serializers.FileField()
    product_id = serializers.IntegerField(required=False)
    deal_id = serializers.IntegerField(required=False)


class DeskTechDocIn(DeskTechDocPassport):
    """Правка паспорта документа (файл не меняется)."""


class DeskTechDocReviewIn(serializers.Serializer):
    """Решение по документу, присланному партнёром (FX-2)."""

    decision = serializers.ChoiceField(choices=["approve", "reject"])
    client_visible = serializers.BooleanField(
        required=False, help_text="Только при approve: видно ли клиенту. Пусто — по умолчанию вида документа."
    )


class DeskHsCode(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    unit_name = serializers.CharField()
    extra_unit_name = serializers.CharField()
    level = serializers.IntegerField()
    valid_from = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)
    is_active = serializers.BooleanField()
    source = serializers.CharField()


class DeskHsCodeIn(serializers.Serializer):
    code = serializers.CharField(required=False, help_text="Только при создании: 2, 4, 6, 8 или 10 цифр.")
    name = serializers.CharField(required=False, allow_blank=True)
    unit_name = serializers.CharField(required=False, allow_blank=True, max_length=64)
    extra_unit_name = serializers.CharField(required=False, allow_blank=True, max_length=64)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_until = serializers.DateField(required=False, allow_null=True)


class DeskExchangeRate(serializers.Serializer):
    id = serializers.IntegerField()
    currency = serializers.CharField()
    rate_to_uzs = serializers.CharField()
    rate_date = serializers.DateField()
    source = serializers.CharField(help_text="CBU (автозагрузка ЦБ РУз) или MANUAL.")
