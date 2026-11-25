"""Кандидаты в номенклатуру: строка КП без товара рождает карточку-черновик.

Наблюдение владельца 03-08: «клиент шлёт заявку на позиции, которых у продавца нет; КП
формируется из воздуха; после сделки товаров как не было, так и нет; ТН ВЭД и сроки перед
отправкой заполняются — а куда пишутся, непонятно». Замер подтвердил: 90 из 98 строк КП (92%)
шли мимо каталога, и введённое продавцом знание умирало вместе с КП.

**Эталон — catalog enablement (SAP Ariba, Coupa):** позиция вне каталога (free-text) не
запрещается — она уходит в очередь, и из повторяющихся рождаются каталожные карточки. Odoo даёт
то же одним движением: «создать товар из строки заказа». Запрещать КП по несуществующему товару
нельзя — это рынок запчастей по чертежам (SAP зовёт такое one-time material).

Канон модуля:

* **Одна сущность на весь жизненный цикл.** Кандидат — это `Product` в статусе `DRAFT`, а не
  отдельная таблица: Akeneo и Pimcore ведут карточку через состояния, не через копии.
* **Владелец — продавец** (`owner_company`), гибрид Grainger: у каждого своя карточка, платформа
  сводит дубли в мастер-запись позже. Решение владельца 03-08 по рекомендации бенчмарка.
* **Дедупликация до создания.** Ключ — бренд+MPN либо ГОСТ/чертёж (промышленный стандарт
  Grainger/Würth; GTIN для запчастей бессмыслен и убран из проекта ещё 2026-06-23). Совпало —
  не плодим карточку, а поднимаем счётчик спроса.
* **Знание строки переносится в карточку.** ТН ВЭД, код единицы, срок — то, ради чего всё
  затевалось: второй раз продавец их не вводит.
* **AI здесь не участвует.** Всё детерминировано; обогащение текстом — отдельный, уже
  существующий путь (`catalog/ai_enrich.py`), и оно всегда черновик под правку человека.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Поля строки КП, которые переносятся в карточку. Значение переносится ТОЛЬКО в пустое поле:
#: карточка — источник правды, строка лишь пополняет то, чего в ней ещё нет.
LINE_TO_CARD_FIELDS = (
    ("hs_code", "hs_code"),
    ("gost_drawing", "gost_drawing"),
    ("mpn", "manufacturer_part_number"),
)


def _clean(value) -> str:
    return (value or "").strip()


def _line_title(item) -> str:
    """Имя для карточки: сначала нормализованное AI, затем сырое из заявки, затем код."""
    return (
        _clean(getattr(item, "name_canonical", ""))
        or _clean(getattr(item, "imported_raw_name", ""))
        or _clean(getattr(item, "mpn", ""))
        or _clean(getattr(item, "gost_drawing", ""))
    )


def find_existing_card(item, owner_company):
    """Карточка того же продавца, описывающая ЭТУ позицию, либо None.

    Ключ идентичности промышленной запчасти — артикул производителя или ГОСТ/чертёж
    (Grainger/Würth); по ним ищем в первую очередь.

    ТОЧНОЕ совпадение имени — обязательный ФОЛБЭК, а не роскошь: у большинства строк заявки нет
    ни артикула, ни чертежа (одно имя из Excel клиента), и без него каждая отправка КП плодила
    бы новый дубль той же позиции — поймано на первом же живом прогоне волны A. Сравнение
    точное и только ВНУТРИ карточек одного продавца: там одинаковое имя означает одну позицию.

    Похожие (а не совпадающие) имена карточек не сливаем — это подсказка человеку, а не
    основание; иначе «подшипник буксовый», который есть у каждого второго, склеил бы разные
    детали.

    СЦ-10: «то же имя» — по ключу `catalog.naming.name_key` (регистр, «ё», пробелы, знаки препинания и латинские
    буквы-двойники не важны). Архивная карточка (в том числе слитый дубль) строку не принимает; из одинаковых —
    опубликованная, затем старейшая.
    """
    from django.db.models import Case, IntegerField, Value, When

    from catalog.models import Product
    from catalog.naming import MAX_LENGTH, name_key

    if owner_company is None:
        return None
    mine = (
        Product.objects.filter(owner_company=owner_company)
        .exclude(status__code="ARCHIVED")
        .order_by(
            Case(When(status__code="PUBLISHED", then=Value(0)), default=Value(1), output_field=IntegerField()), "pk"
        )
    )
    mpn = _clean(getattr(item, "mpn", ""))
    if mpn:
        found = mine.filter(manufacturer_part_number__iexact=mpn).first()
        if found:
            return found
    gost = _clean(getattr(item, "gost_drawing", ""))
    if gost:
        found = mine.filter(gost_drawing__iexact=gost).first()
        if found:
            return found
    # Карточка хранит name[:255] (`ensure_candidate_for_line`) — ключ строки той же длины.
    key = name_key(_line_title(item)[:MAX_LENGTH])
    if key:
        return mine.filter(name_key=key).first()
    return None


def capture_line_knowledge(item, product) -> list[str]:
    """Перенести в карточку то, что продавец заполнил в строке КП.

    Это и есть ответ на вопрос «куда пишутся ТН ВЭД и сроки»: раньше — никуда. Заполняем ТОЛЬКО
    пустые поля карточки, чтобы строка одного КП не переписывала выверенный справочник.
    """
    updated: list[str] = []
    for line_field, card_field in LINE_TO_CARD_FIELDS:
        value = _clean(getattr(item, line_field, ""))
        if value and not _clean(getattr(product, card_field, "")):
            setattr(product, card_field, value)
            updated.append(card_field)

    # Единица измерения приходит нормализованной по UN/ECE Rec 20 — берём справочник по коду.
    unit_code = _clean(getattr(item, "unit_code", ""))
    if unit_code and product.uom_id is None:
        from master_data.models import UnitOfMeasure

        uom = UnitOfMeasure.objects.filter(code__iexact=unit_code).first()
        if uom:
            product.uom = uom
            updated.append("uom")
    return updated


def _domain_type_for(kind: str | None):
    """Тип карточки по типу строки расчёта (ADR-0027 п. 2): услуга — `SERVICES`, иначе товар."""
    from catalog.models import DomainType

    code = DomainType.SERVICES if kind == "service" else DomainType.GENERAL_GOODS
    return DomainType.objects.filter(code=code).first()


@transaction.atomic
def ensure_candidate_for_line(item, owner_company, *, deal=None, kind: str | None = None):
    """Найти или создать карточку-кандидата для строки КП без товара.

    Возвращает `(product, created)`. `None, False` — если из строки нечего описывать
    (пустая строка, раздел, примечание) или продавец неизвестен.
    """
    from catalog.models import Product, ProductStatus

    if owner_company is None or getattr(item, "product_id", None):
        return None, False
    title = _line_title(item)
    if not title:
        return None, False

    existing = find_existing_card(item, owner_company)
    if existing is not None:
        old_hs = existing.hs_code or ""
        fields = capture_line_knowledge(item, existing)
        existing.demand_count = (existing.demand_count or 0) + 1
        existing.last_requested_at = timezone.now()
        fields += ["demand_count", "last_requested_at"]
        existing.save(update_fields=list(dict.fromkeys(fields)))
        if "hs_code" in fields:
            from catalog.services import log_hs_code_change

            log_hs_code_change(existing, old_hs, None, origin="quote_line")
        return existing, False

    draft_status = ProductStatus.objects.filter(code="DRAFT").first()
    product = Product(
        name=title[:255],
        owner_company=owner_company,
        status=draft_status,
        source_deal=deal if deal is not None else getattr(getattr(item, "quote", None), "deal", None),
        domain_type=_domain_type_for(kind),
        demand_count=1,
        last_requested_at=timezone.now(),
    )
    capture_line_knowledge(item, product)
    # `Product.save()` вызывает full_clean(); карточка-кандидат по определению неполна, поэтому
    # доменную валидацию групп оборудования она пройти не обязана — та требует уже сохранённый
    # pk и срабатывает на публикации (см. `completeness`).
    product.save()
    return product, True


def _line_kind(item) -> str | None:
    # Нет `CalcLine` (строка КП вне расчёта) — `RelatedObjectDoesNotExist`, наследник `AttributeError`.
    return getattr(getattr(item, "calc", None), "kind", None)


def _owner_for(quote):
    """Владелец карточек — наша компания (ADR-0027 п. 6); без неё — продавец КП."""
    from django.core.exceptions import ImproperlyConfigured

    from accounts.models import Company
    from core.tenant import own_company_id

    try:
        company_id = own_company_id()
    except ImproperlyConfigured:
        company_id = None
    if company_id:
        return Company.objects.filter(pk=company_id).first()
    if quote is None:
        return None
    from crm.services.quotes import _quote_seller_company

    return _quote_seller_company(quote)


def card_for_text(title: str, *, deal=None, quote=None):
    """Карточка для строки документа, у которой есть только название (ручной счёт): найденная или новый черновик.

    Тот же поиск дубля и та же карточка-черновик, что у строки КП (ADR-0027 п. 1, 3). None — нечем описать.
    """
    from types import SimpleNamespace

    owner = _owner_for(quote)
    line = SimpleNamespace(imported_raw_name=_clean(title), product_id=None, quote=quote)
    product, _created = ensure_candidate_for_line(line, owner, deal=deal)
    return product


@transaction.atomic
def link_line(item, owner_company, *, deal=None) -> bool:
    """Связать одну строку без карточки с найденной или новой карточкой-черновиком. True — строка связана."""
    product, created = ensure_candidate_for_line(item, owner_company, deal=deal, kind=_line_kind(item))
    if product is None:
        return False
    item.product = product
    fields = ["product"]
    # ADR-0027 п. 10: строка без своей единицы берёт единицу найденной карточки.
    uom = product.uom if product.uom_id else None
    if not created and uom is not None and len(uom.code) <= 8 and not _clean(item.unit_code) and not _clean(item.unit):
        item.unit_code, item.unit = uom.code, uom.name[:32]
        fields += ["unit_code", "unit"]
    item.save(update_fields=fields, skip_recalculate=True)
    return True


def link_quote_lines(quote, *, hold_hinted: bool = False) -> dict:
    """Каждая строка КП без карточки получает карточку (ADR-0027 п. 1). Идемпотентна: связанные строки не трогает.

    Разделы и примечания не связываются; строка без названия — тоже (её нечем описать). `hold_hinted` — расчёт:
    строка с подсказкой похожей карточки (`CalcLine.catalog_hint`, СЦ-10) ждёт решения человека и черновик не
    получает; отправка КП и счёт вызывают без него — в документе клиенту у строки карточка есть всегда.
    """
    from django.db.models import Q
    from sales.models import QuoteItem

    result = {"linked": 0, "skipped": 0}
    rows = quote.items.filter(display_type=QuoteItem.DisplayType.ITEM, product__isnull=True)
    if hold_hinted:
        rows = rows.filter(Q(calc__isnull=True) | Q(calc__catalog_hint__isnull=True))
    items = list(rows.select_related("quote__deal"))
    if not items:
        return result
    owner = _owner_for(quote)
    if owner is None:
        result["skipped"] = len(items)
        return result
    deal = getattr(quote, "deal", None)
    for item in items:
        if link_line(item, owner, deal=deal):
            result["linked"] += 1
        else:
            result["skipped"] += 1
    return result


def suggest_card(item, owner_company):
    """Похожая карточка для подсказки человеку (СЦ-10), НЕ для привязки.

    То же первое слово ключа имени и общий код с цифрами без конфликта семьи кодов («Рельс Р65, длина 25 м» →
    «Рельс Р65 ГОСТ Р 51685», но не «Рельс Р50 …»); в строке нет цифр — имя карточки начинается с имени строки.
    Видимые: опубликованные и свои, без архива. Порядок: тот же ключ, больше общих кодов, опубликованная, старейшая.
    """
    from django.db.models import Q

    from catalog.models import Product
    from catalog.naming import MAX_LENGTH, code_tokens, codes_conflict, name_key

    key = name_key(_line_title(item)[:MAX_LENGTH])
    words = key.split()
    if not words:
        return None
    codes = code_tokens(key)
    visible = Q(status__code="PUBLISHED")
    if owner_company is not None:
        visible |= Q(owner_company=owner_company)
    cards = (
        Product.objects.filter(visible)
        .exclude(status__code="ARCHIVED")
        .filter(Q(name_key=words[0]) | Q(name_key__startswith=words[0] + " "))
        .select_related("status")
        .only("id", "name", "name_key", "status__code")[:200]
    )
    best, best_rank = None, None
    for card in cards:
        if codes:
            shared = len(codes & set(card.name_key.split()))
            if not shared or codes_conflict(codes, card.name_key):
                continue
        else:
            shared = 0
            if not (card.name_key + " ").startswith(key + " "):
                continue
        rank = (0 if card.name_key == key else 1, -shared, 0 if card.status.code == "PUBLISHED" else 1, card.pk)
        if best_rank is None or rank < best_rank:
            best, best_rank = card, rank
    return best


def is_unconfirmed_card(product) -> bool:
    """Карточка заведена автоматически из слов клиента (расчёт, КП) и человек её не подтвердил: статус `DRAFT` и `source_deal`.

    Её название — слова клиента, а не «наша карточка»: партнёру оно уходит только после подтверждения (публикация
    карточки или название от сотрудника — аудит конфиденциальности 2026-11-25, В-2)."""
    return (
        product is not None
        and getattr(getattr(product, "status", None), "code", None) == "DRAFT"
        and product.source_deal_id
        is not None  # заведена строкой сделки; черновик, созданный человеком в каталоге, — нет
    )


def is_own_draft(item) -> bool:
    """Карточка строки — черновик, который эта строка сама создала: спрос 1, та же сделка (ADR-0027 п. 5)."""
    product = item.product if item.product_id else None
    if product is None or getattr(product.status, "code", None) != "DRAFT":
        return False
    return (product.demand_count or 0) <= 1 and product.source_deal_id == getattr(item.quote, "deal_id", None)


def drop_unused_draft(product_id: int | None) -> bool:
    """Черновик, на который больше не ссылается ни одна строка КП и счёта, удаляется: строку сопоставили с каталогом."""
    from catalog.models import Product

    if not product_id:
        return False
    draft = Product.objects.filter(
        pk=product_id, status__code="DRAFT", quote_items__isnull=True, invoice_items__isnull=True
    ).first()
    if draft is None:
        return False
    draft.delete()
    return True


def set_draft_kind(item, kind: str) -> None:
    """Тип своего черновика меняется вместе со строкой: товар ↔ услуга."""
    product = item.product
    product.domain_type = _domain_type_for(kind)
    product.save(update_fields=["domain_type"])


def relink_renamed_line(item, old_name: str) -> None:
    """Строку переименовали в расчёте (ADR-0027 п. 5).

    Черновик, который эта строка сама создала (спрос 1, та же сделка), переименовывается вместе с ней; иначе строка
    отвязывается и заново проходит поиск или создание карточки.
    """
    product = item.product if item.product_id else None
    if product is None or _clean(old_name) == _clean(item.imported_raw_name):
        return
    if getattr(product.status, "code", None) != "DRAFT":
        return
    title = _line_title(item)
    if not title:
        return
    if is_own_draft(item):
        owner = _owner_for(item.quote)
        other = find_existing_card(item, owner) if owner is not None else None
        if other is not None and other.pk != product.pk:  # новое имя уже есть в каталоге — второй карточки не будет
            item.product = other
            item.save(update_fields=["product"], skip_recalculate=True)
            other.demand_count = (other.demand_count or 0) + 1
            other.save(update_fields=["demand_count"])
            drop_unused_draft(product.pk)
            return
        product.name = title[:255]
        product.save(update_fields=["name"])
        return
    product.demand_count = max(0, (product.demand_count or 0) - 1)
    product.save(update_fields=["demand_count"])
    item.product = None
    owner = _owner_for(item.quote)
    if owner is not None:
        link_line(item, owner, deal=item.quote.deal)


def capture_quote_lines(quote) -> dict:
    """Отправка КП: последняя точка, где строка без карточки получает карточку (ADR-0027 п. 1).

    Никогда не бросает наружу: наполнение каталога не должно ломать отправку КП клиенту.
    """
    try:
        return link_quote_lines(quote)
    except Exception:  # noqa: BLE001 — наполнение каталога не должно ронять отправку КП
        logger.exception("catalog: не удалось связать строки КП %s с каталогом", getattr(quote, "pk", None))
        return {"linked": 0, "skipped": 0}
