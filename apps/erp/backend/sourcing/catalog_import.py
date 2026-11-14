"""Self-service seller catalog import engine (true-PIM).

A seller uploads an .xlsx of their products + commercial terms. We:
  * resolve/create the **Brand** (catalog.Manufacturer) by name,
  * de-duplicate the canonical **Product** by (brand + manufacturer part number)
    or GOST/drawing — so two suppliers of the same item share ONE PIM card,
  * upsert the seller's **SupplierOffer** (price / currency / stock / lead / MOQ).

Файл несёт и ТАКСОНОМИЮ карточки — категорию, код ТН ВЭД и направление. Без них загрузка
физически не могла дать публикуемую карточку: порог публикации (`catalog/completeness.py`)
требует ровно эти поля, и прайс-лист на 3000 строк давал 3000 черновиков, о чём отчёт молчал.
Поэтому же отчёт теперь считает, сколько карточек порог не пройдут и чего им не хватает.

The supplier is the company the VIEW resolved: the uploader's own seller company
(self-service path) or a supplier chosen explicitly by a back-office employee with the
catalog and supply rights (CAT-1, `supplier_company_id`) — never a column in the file.

PART-2 — загрузку из кабинета партнёра запускает контакт компании (`contact_id`), а не пользователь ERP: он же автор
предложений по полям (`ProductFieldProposal.contact`) и «подтвердил актуальность» на записанных ценах. Поставщик — компания
сессии кабинета, выбрать другого нельзя; новые карточки — нашего каталога (владелец — своя компания), поставщик — источник
данных. Свою карточку партнёр правит прайсом, пока она «черновик» или «возвращена»; на проверке и опубликованная — только
предложения по полям.

CAT-1 — чужие карточки не перезаписываются. Совпадение по бренду+MPN (или ГОСТ/чертежу) с
карточкой, которую завёл ДРУГОЙ поставщик или которая уже не черновик, обновляет только
предложение поставщика; расхождения полей уходят в `catalog.ProductFieldProposal` на одобрение
(SAP Ariba catalog upload: загрузка → сопоставление → одобрение). Срок действия цены — на весь
файл из формы или колонками «Действует с / до» (Odoo `product.supplierinfo` date_start/date_end). Each row is processed in its own savepoint
so one bad row can't poison the batch; per-row problems are returned as a
structured error list. `dry_run=True` runs the full pipeline and rolls back,
returning the same counts for a preview.

Business logic lives here (Rule 8); the Celery task is a thin wrapper.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO

import pandas as pd
import pghistory
from django.db import transaction

from catalog.lead_time import lead_days_from_text

logger = logging.getLogger(__name__)

MAX_EXCEL_ROWS = 50_000
MAX_REPORTED_ERRORS = 200
#: Предупреждения живут по тем же правилам, что и ошибки: показываем первые N, считаем все.
MAX_REPORTED_WARNINGS = MAX_REPORTED_ERRORS

# Logical field -> substring aliases (matched against lower-cased headers).
# Order matters: more specific fields claim their column before generic ones
# (e.g. "артикул производителя" is taken by `mpn`, leaving bare "артикул" for
# `supplier_sku`).
# NOTE: resolution order matters — the more specific identifier columns (mpn,
# gost, supplier_sku) claim their column BEFORE `brand`, because the brand alias
# "производитель" is a substring of "артикул производителя" (MPN) and would
# otherwise steal it.
COLUMN_ALIASES = {
    # `category` стоит ПЕРВЫМ намеренно. Алиас «категор» не встречается ни в одном заголовке
    # остальных полей, так что ничего у них он не отнимает; зато заголовок «Категория товара»
    # иначе достался бы полю `name` (у него алиас «товар»), и карточки назвались бы категориями.
    "category": ["категор", "category"],
    "name": ["name", "наименование", "товар", "название", "изделие"],
    "mpn": ["артикул производителя", "mpn", "part number", "part_no", "заводской", "номер детали"],
    "gost": ["гост", "gost", "чертеж", "drawing"],
    "supplier_sku": ["артикул поставщика", "supplier sku", "ваш артикул", "артикул продавца", "артикул"],
    "brand": ["бренд", "brand", "производитель", "manufacturer", "марка"],
    "description": ["описание", "desc", "примечание"],
    "uom": ["ед", "изм", "uom", "unit"],
    "price": ["цена", "price", "стоимость"],
    "currency": ["валюта", "currency"],
    "stock": ["наличие", "склад", "stock"],
    "lead": ["срок", "lead", "поставк"],
    "moq": ["мин", "moq", "минимальн"],
    # Остальные новинки — в САМОМ КОНЦЕ: так они могут занять только колонку, которую не
    # забрал никто до них, и разбор существующих файлов не меняется. Алиасы узкие осознанно:
    # общее «код» отобрало бы у артикула «Код поставщика», а «направление» безопасно только
    # целиком — с «наименованием» оно не пересекается ни одной подстрокой.
    "hs_code": ["тн вэд", "тнвэд", "тн-вэд", "hs code", "hs_code", "hs-code", "hscode"],
    "domain_type": ["направление", "домен", "domain"],
    # CAT-1: срок действия цены построчно (по желанию; на весь файл — поле формы).
    "valid_from": ["действует с", "valid from"],
    "valid_until": ["действует до", "valid until", "valid to"],
}


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    offers_upserted: int = 0
    #: CAT-1: новые предложения и обновлённые цены — отдельно (отчёт «новые / обновлённые цены»).
    offers_created: int = 0
    offers_updated: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)
    #: Мягкие замечания: строка ЗАГРУЖЕНА, но к ней есть вопрос (код ТН ВЭД вне справочника).
    #: Предупреждение не откатывает строку и не попадает в `skipped` — иначе это был бы блок.
    warnings: list = field(default_factory=list)
    warning_count: int = 0
    #: Сколько строк файла не попало в разбор из-за `MAX_EXCEL_ROWS` (раньше исчезали молча).
    rows_truncated: int = 0
    #: Сколько затронутых карточек НЕ пройдут порог публикации и чего им не хватает.
    unpublishable: int = 0
    missing_breakdown: list = field(default_factory=list)
    #: CAT-1: расхождения с чужой или опубликованной карточкой — на одобрение, карточка не тронута.
    proposals: list = field(default_factory=list)
    proposal_count: int = 0
    dry_run: bool = False

    def add_error(self, row_number: int, message: str) -> None:
        self.skipped += 1
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append({"row": row_number, "message": message})

    def add_warning(self, row_number: int, message: str) -> None:
        self.warning_count += 1
        if len(self.warnings) < MAX_REPORTED_WARNINGS:
            self.warnings.append({"row": row_number, "message": message})

    def add_proposal(self, row_number: int, proposal: dict) -> None:
        self.proposal_count += 1
        if len(self.proposals) < MAX_REPORTED_ERRORS:
            self.proposals.append({"row": row_number, **proposal})

    def as_dict(self) -> dict:
        return {
            "status": "success",
            "dry_run": self.dry_run,
            "created": self.created,
            "updated": self.updated,
            "offers_upserted": self.offers_upserted,
            "offers_created": self.offers_created,
            "offers_updated": self.offers_updated,
            "proposal_count": self.proposal_count,
            "proposals": self.proposals,
            "skipped": self.skipped,
            # `error_count`/`warning_count` считают ВСЕ находки, а списки усечены до
            # MAX_REPORTED_*: интерфейсу этого достаточно, чтобы сказать «показаны первые 200
            # из N», а не делать вид, что их всего 200.
            "error_count": self.skipped,
            "errors": self.errors,
            "warning_count": self.warning_count,
            "warnings": self.warnings,
            "rows_truncated": self.rows_truncated,
            "unpublishable": self.unpublishable,
            "missing_breakdown": self.missing_breakdown,
            # Backward-compatible key consumed by the existing frontend.
            "items_processed": self.created + self.updated,
        }


def _resolve_columns(columns) -> dict:
    """Map each logical field to an actual column, claiming each column once."""
    resolved = {}
    claimed = set()
    for logical, aliases in COLUMN_ALIASES.items():
        for column in columns:
            if column in claimed:
                continue
            if any(alias in column for alias in aliases):
                resolved[logical] = column
                claimed.add(column)
                break
        else:
            resolved[logical] = None
    return resolved


def _cell(row, column) -> str:
    """Trimmed string for a cell; '' for missing/NaN."""
    if not column:
        return ""
    value = row.get(column)
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _parse_decimal(text: str):
    """Parse a price cell. Returns None for a blank cell (name-only row → no offer).

    A non-blank value must be a number > 0 — a negative or zero price is a data
    error, not a valid offer (M3). We reject it with a stable code so the row is
    rolled back and reported instead of silently writing a bogus offer.
    """
    if not text:
        return None
    try:
        value = Decimal(text.replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError("PRICE_NOT_A_NUMBER")
    if value <= 0:
        raise ValueError("PRICE_NOT_POSITIVE")
    return value


def _parse_int(text: str, default: int) -> int:
    if not text:
        return default
    try:
        return int(float(text.replace(" ", "").replace(",", ".")))
    except (ValueError, TypeError):
        return default


def _hs_digits(text: str) -> str:
    """Цифры кода ТН ВЭД из ячейки.

    Excel отдаёт числовую ячейку как `8482100000.0` — дробный хвост принадлежит представлению
    числа, а не коду, и без его отсечения десятизначный код превращался бы в одиннадцатизначный.
    """
    text = (text or "").strip()
    whole, dot, frac = text.partition(".")
    if dot and whole.isdigit() and set(frac) <= {"0"}:
        text = whole
    return "".join(char for char in text if char.isdigit())


def _parse_date(text: str):
    """Дата ячейки: `ГГГГ-ММ-ДД` (Excel отдаёт дату как `2026-12-31 00:00:00`) или `ДД.ММ.ГГГГ`; пусто — None."""
    from datetime import date, datetime

    text = (text or "").strip()
    if not text:
        return None
    for fmt, size in (("%Y-%m-%d", 10), ("%d.%m.%Y", 10)):
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    if isinstance(text, date):  # pragma: no cover — ячейки читаются строками (dtype=str)
        return text
    raise ValueError("VALID_DATE_INVALID")


@dataclass
class _Ctx:
    """Per-import shared state (caches + lookups) — avoids per-row DB queries."""

    supplier: object
    Product: object
    Manufacturer: object
    SupplierOffer: object
    uom: dict
    currency: dict
    stock: dict
    domain: dict
    #: Домен по КОДУ и по НАЗВАНИЮ в нижнем регистре — продавец пишет в файле любое из двух.
    domain_by_key: dict
    #: Категория по названию в нижнем регистре. Таксономия платформенная: импорт её ЧИТАЕТ.
    category_by_name: dict
    #: Вердикт справочника ТН ВЭД по каждому коду файла — считается пачкой ДО обхода строк.
    hs_status: dict
    hs_code_max_length: int
    status_draft: object
    brand_cache: dict
    #: Затронутые карточки по pk (одна и та же строка может встретиться дважды) — по ним
    #: считается сводка публикуемости.
    touched_products: dict
    dry_run: bool
    #: CAT-1: предложения по полям чужих карточек, кто загрузил, срок цены на весь файл.
    Proposal: object = None
    actor: object = None
    #: PART-2: контакт кабинета партнёра, загрузивший файл (вместо пользователя ERP).
    contact: object = None
    valid_from: object = None
    valid_until: object = None
    #: Владелец новых карточек: своя компания на пути сотрудника, иначе сам поставщик (путь продавца).
    owner: object = None


def _resolve_brand(ctx: _Ctx, name: str):
    """Find a Brand by name, creating it on demand (catalog grows from uploads).

    In dry-run we never create — an unseen brand resolves to None, which only
    softens product de-dup for the preview.
    """
    if not name:
        return None
    key = name.lower()
    if key in ctx.brand_cache:
        return ctx.brand_cache[key]
    brand = ctx.Manufacturer.objects.filter(name__iexact=name).first()
    if not brand and not ctx.dry_run:
        # Тот же нормализатор, что у формы карточки (catalog.services.find_or_create_manufacturer).
        from catalog.services import find_or_create_manufacturer

        brand = find_or_create_manufacturer(name)
    ctx.brand_cache[key] = brand
    return brand


def _find_existing_product(ctx: _Ctx, brand, mpn: str, gost: str):
    """De-dup key: (brand + manufacturer part number), else GOST/drawing.

    `select_related("domain_type")` — не украшение: домен читает и порог публикации, и
    сводка отчёта, и без него каждая обновлённая карточка стоила бы лишний запрос.
    """
    query = ctx.Product.objects.select_related("domain_type")
    if brand and mpn:
        return query.filter(brand=brand, manufacturer_part_number__iexact=mpn).first()
    if gost:
        query = query.filter(gost_drawing__iexact=gost)
        if brand:
            query = query.filter(brand=brand)
        return query.first()
    return None


def _save_product(product) -> None:
    product.save()


def _update_product(ctx: _Ctx, existing, fields: dict, brand, uom) -> None:
    """Обновить существующую карточку значениями строки (пустая ячейка ничего не стирает)."""
    existing.name = fields["name"]
    if fields["description"]:
        existing.description = fields["description"]
    if brand:
        existing.brand = brand
    if fields["mpn"]:
        existing.manufacturer_part_number = fields["mpn"]
    if fields["gost"]:
        existing.gost_drawing = fields["gost"]
    if uom:
        existing.uom = uom
    if fields["category"]:
        existing.category = fields["category"]
    if fields["hs_code"]:
        existing.hs_code = fields["hs_code"]
    # ЯВНО указанное направление применяется и при обновлении: иначе домен карточки, однажды
    # угаданный по ключевым словам, нельзя было исправить ничем, кроме ручной правки. ДОГАДКА
    # же остаётся только для создания — молча переклассифицировать чужую готовую карточку по
    # совпадению слова в наименовании нельзя.
    if fields["domain"]:
        existing.domain_type = fields["domain"]
    # Backfill ownership for an orphaned card (C3), but never hijack a product
    # another tenant already owns — de-dup matches globally on brand+MPN.
    if ctx.owner and existing.owner_company_id is None:
        existing.owner_company = ctx.owner
    _save_product(existing)


def _create_product(ctx: _Ctx, fields: dict, brand, uom):
    from .tasks import route_domain

    domain = fields["domain"] or ctx.domain.get(route_domain(fields["name"]))
    product = ctx.Product(
        name=fields["name"],
        description=fields["description"],
        brand=brand,
        manufacturer_part_number=fields["mpn"],
        gost_drawing=fields["gost"],
        domain_type=domain,
        category=fields["category"],
        hs_code=fields["hs_code"],
        status=ctx.status_draft,
        uom=uom,
        # Stamp the importing seller as owner so they can see/manage their own cards
        # (C3) — without this, imported products are orphaned and invisible to them.
        # CAT-1: прайс завода, загруженный сотрудником, — карточка нашего каталога (владелец — своя компания),
        # а завод записан источником данных.
        owner_company=ctx.owner,
        source_supplier=ctx.supplier,
    )
    _save_product(product)
    return product


def _find_by_own_offer(ctx: _Ctx, fields: dict, supplier_sku: str):
    """Строка без бренда+MPN и без ГОСТ: карточка по предложению ЭТОГО поставщика (артикул поставщика, иначе наименование).

    Без этого повторная загрузка того же прайса плодила бы карточку на каждую строку без ключа (Odoo сопоставляет
    строку прайса с товаром по `product.supplierinfo.product_code` поставщика так же).
    """
    if not ctx.supplier or fields["mpn"] or fields["gost"]:
        return None
    offers = ctx.SupplierOffer.objects.filter(supplier=ctx.supplier).select_related("product__domain_type")
    match = offers.filter(supplier_sku__iexact=supplier_sku).first() if supplier_sku else None
    if match is None:
        by_card_name = offers.filter(product__name__iexact=fields["name"]).order_by("id")
        if ctx.contact is not None:
            # Загрузка из кабинета (PART-2): название чужой неопубликованной карточки угадывать нельзя — совпадение по нему
            # было бы подсказкой «такая карточка есть» (счётчики, цена не дописывается). По названию карточки ищем только
            # свои и опубликованные; скрытую — лишь по тому, что партнёр прислал сам (`supplier_item_name`).
            from django.db.models import Q

            own_or_published = Q(product__source_supplier_id=ctx.supplier.pk) | Q(product__status__code="PUBLISHED")
            by_card_name = by_card_name.filter(own_or_published)
            match = (
                by_card_name.first() or offers.filter(supplier_item_name__iexact=fields["name"]).order_by("id").first()
            )
        else:
            match = by_card_name.first()
    return match.product if match else None


#: Статусы карточки, поля которой прайс своего поставщика меняет: черновик и возвращённая с причиной (PART-2: партнёр
#: исправляет её тем же прайсом). «На проверке», опубликованная и архивная — только предложения по полям.
EDITABLE_STATUS_CODES = ("DRAFT", "RETURNED")


def _is_foreign_card(ctx: _Ctx, product) -> bool:
    """Карточку завёл другой поставщик (или сотрудник) или она уже не черновик — прайс её полей не меняет (CAT-1).

    «Свою» карточку поставщика узнаём по `source_supplier` (заведена из его прайса); у старых карточек без него — по
    владельцу, как до CAT-1 (путь продавца: своя компания загружает свой каталог).
    """
    status_code = getattr(product.status, "code", None)
    if status_code and status_code not in EDITABLE_STATUS_CODES:
        return True
    supplier_id = getattr(ctx.supplier, "pk", None)
    if product.source_supplier_id is not None:
        return product.source_supplier_id != supplier_id
    owner_id = product.owner_company_id
    return owner_id is not None and owner_id != supplier_id


def _hidden_from_contact(ctx: _Ctx, product) -> bool:
    """Загрузка из кабинета партнёра совпала с карточкой, которой он не источник и которая не опубликована (PART-2).

    Такую карточку партнёр не должен ни видеть, ни угадывать по отчёту (предложения по полям, полнота): цена
    привязывается к ней молча, а по отчёту это просто «сопоставлено». Опубликованный слой публичен — для него отчёт прежний.
    """
    if ctx.contact is None:
        return False
    supplier_id = getattr(ctx.supplier, "pk", None)
    status_code = getattr(product.status, "code", None)
    return status_code != "PUBLISHED" and product.source_supplier_id != supplier_id


def _display(value) -> str:
    if value is None:
        return ""
    return str(getattr(value, "name", value) or "")


def _card_differences(existing, fields: dict, uom) -> list:
    """Поля строки, которые расходятся с карточкой: `(поле, было, стало, id справочника)`. Пустая ячейка — не расхождение."""
    out = []
    if fields["name"] and fields["name"].strip() != (existing.name or "").strip():
        out.append(("name", existing.name or "", fields["name"].strip(), None))
    if fields["description"] and fields["description"] != (existing.description or ""):
        out.append(("description", existing.description or "", fields["description"], None))
    if fields["gost"] and fields["gost"].lower() != (existing.gost_drawing or "").lower():
        out.append(("gost_drawing", existing.gost_drawing or "", fields["gost"], None))
    if fields["hs_code"] and fields["hs_code"] != (existing.hs_code or ""):
        out.append(("hs_code", existing.hs_code or "", fields["hs_code"], None))
    for name, model_field, value in (
        ("category", "category", fields["category"]),
        ("uom", "uom", uom),
        ("domain_type", "domain_type", fields["domain"]),
    ):
        if value is not None and getattr(existing, f"{model_field}_id") != value.pk:
            out.append((name, _display(getattr(existing, model_field)), _display(value), value.pk))
    return out


def _propose(ctx: _Ctx, product, field_name: str, current: str, proposed: str, ref) -> bool:
    """Открыть или обновить предложение по полю. False — значение уже отклонено человеком (повторно не предлагаем)."""
    Proposal = ctx.Proposal
    scope = {"product": product, "field": field_name, "supplier": ctx.supplier}
    if Proposal.objects.filter(**scope, status=Proposal.Status.REJECTED, proposed_value=proposed).exists():
        return False
    pending = Proposal.objects.filter(**scope, status=Proposal.Status.PENDING).first()
    if pending is None:
        Proposal.objects.create(
            **scope,
            current_value=current,
            proposed_value=proposed,
            proposed_ref=ref,
            created_by=ctx.actor,
            contact=ctx.contact,
        )
    elif (pending.proposed_value, pending.proposed_ref, pending.current_value) != (proposed, ref, current):
        pending.proposed_value, pending.proposed_ref, pending.current_value = proposed, ref, current
        pending.save(update_fields=["proposed_value", "proposed_ref", "current_value", "updated_at"])
    return True


def _propose_differences(ctx: _Ctx, existing, fields: dict, uom) -> list:
    proposals = []
    for field_name, current, proposed, ref in _card_differences(existing, fields, uom):
        if _propose(ctx, existing, field_name, current, proposed, ref):
            proposals.append(
                {
                    "product_id": existing.pk,
                    "product_name": existing.name,
                    "field": field_name,
                    "current": current,
                    "proposed": proposed,
                }
            )
    return proposals


def _apply_product(ctx: _Ctx, fields: dict, supplier_sku: str = ""):
    """Create or update the canonical Product card. Returns (product, created, proposals)."""
    brand = _resolve_brand(ctx, fields["brand_name"])
    existing = _find_existing_product(ctx, brand, fields["mpn"], fields["gost"])
    if existing is None:
        existing = _find_by_own_offer(ctx, fields, supplier_sku)
    uom = ctx.uom.get(fields["uom_code"]) if fields["uom_code"] else None

    if existing:
        if _is_foreign_card(ctx, existing):
            if _hidden_from_contact(ctx, existing):
                return existing, False, []  # чужая неопубликованная карточка: партнёру о ней ничего не сообщаем
            return existing, False, _propose_differences(ctx, existing, fields, uom)
        _update_product(ctx, existing, fields, brand, uom)
        return existing, False, []
    return _create_product(ctx, fields, brand, uom), True, []


def _upsert_offer(ctx: _Ctx, product, offer: dict) -> bool:
    """Upsert the supplier's SupplierOffer for this product (unique per supplier). True — предложение новое.

    Срок действия цены пишется, только если он задан (строкой или на весь файл): прайс без срока не стирает срок,
    поставленный раньше вручную.
    """
    defaults = {
        "base_price": offer["price"],
        "currency": offer["currency"],
        "stock_status": offer["stock"],
        "supplier_sku": offer["supplier_sku"],
        # Что поставщик прислал сам (PART-2): по этому кабинет показывает ему сопоставленную чужую карточку
        "supplier_item_name": (offer.get("item_name") or "")[:255],
        "supplier_brand": (offer.get("brand") or "")[:255],
        "supplier_mpn": (offer.get("mpn") or "")[:100],
        "delivery_lead_time": offer["lead"],
        "min_order_qty": offer["moq"],
        "is_active": True,
        "source": ctx.SupplierOffer.Source.PRICE_LIST,
    }
    for key in ("valid_from", "valid_until"):
        if offer.get(key) is not None:
            defaults[key] = offer[key]
    lead_days = lead_days_from_text(offer["lead"])
    if lead_days is not None:  # plan 0.6 (FR-15): the price-list term reaches the calculation as days
        defaults["order_lead_time_days"] = lead_days
    if ctx.contact is not None:
        # Свежий прайс из кабинета сам подтверждает актуальность загруженных цен (PART-2) — кроме цены, срок которой уже
        # прошёл (по дню Ташкента): подтвердить истёкшую цену нельзя ни кнопкой, ни загрузкой.
        from django.utils import timezone

        until = defaults.get("valid_until")
        if until is None:  # срок не задан файлом — остаётся прежний срок предложения, если оно уже есть
            until = (
                ctx.SupplierOffer.objects.filter(product=product, supplier=ctx.supplier)
                .values_list("valid_until", flat=True)
                .first()
            )
        if until is None or until >= timezone.localdate():
            defaults["confirmed_at"] = timezone.now()
            defaults["confirmed_by_contact"] = ctx.contact
    _, created = ctx.SupplierOffer.objects.update_or_create(product=product, supplier=ctx.supplier, defaults=defaults)
    return created


def _row_validity(ctx: _Ctx, row, columns: dict):
    """Срок цены строки: колонка строки, иначе поле формы на весь файл. Конец раньше начала — ошибка строки."""
    from catalog.services import offer_validity_error

    valid_from = _parse_date(_cell(row, columns["valid_from"])) or ctx.valid_from
    valid_until = _parse_date(_cell(row, columns["valid_until"])) or ctx.valid_until
    error = offer_validity_error(valid_from, valid_until)
    if error:
        raise ValueError(error)
    return valid_from, valid_until


def _row_taxonomy(ctx: _Ctx, row, columns: dict):
    """Категория / код ТН ВЭД / направление строки. Возвращает `(значения, предупреждения)`.

    Категория и направление СТРОГИЕ: продавец написал слово, которого в справочнике нет —
    молча проглотить его значит соврать. Категорию при этом импорт только ЧИТАЕТ: таксономия
    платформенная, продавец в неё не пишет (это продуктовое решение, а не недосмотр).

    Код ТН ВЭД, наоборот, МЯГКИЙ (PRODUCT RULE 2): классификатор может быть ещё не загружен, а
    код продавец знает из своей декларации — расхождение со справочником это ПРЕДУПРЕЖДЕНИЕ.
    """
    category_name = _cell(row, columns["category"])
    category = ctx.category_by_name.get(category_name.lower()) if category_name else None
    if category_name and category is None:
        raise ValueError(f"UNKNOWN_CATEGORY:{category_name}")

    domain_text = _cell(row, columns["domain_type"])
    domain = ctx.domain_by_key.get(domain_text.lower()) if domain_text else None
    if domain_text and domain is None:
        raise ValueError(f"UNKNOWN_DOMAIN:{domain_text}")

    warnings = []
    hs_code = _hs_digits(_cell(row, columns["hs_code"]))
    if hs_code and len(hs_code) > ctx.hs_code_max_length:
        # Длиннее поля карточки — записать нельзя, но и ронять строку из-за этого не за что.
        warnings.append(f"HS_CODE_TOO_LONG:{hs_code}")
        hs_code = ""
    elif hs_code:
        verdict = ctx.hs_status.get(hs_code)
        if verdict and not verdict["known"]:
            warnings.append(f"HS_CODE_NOT_IN_CLASSIFIER:{hs_code}")
        elif verdict and not verdict["active"]:
            warnings.append(f"HS_CODE_RETIRED:{hs_code}")

    return {"category": category, "domain": domain, "hs_code": hs_code}, warnings


def _row_commercials(ctx: _Ctx, row, columns: dict):
    """Валюта / наличие / цена строки. Коды сверяются со справочниками строго."""
    currency_code = _cell(row, columns["currency"]).upper()
    currency = ctx.currency.get(currency_code) if currency_code else None
    if currency_code and not currency:
        raise ValueError(f"UNKNOWN_CURRENCY:{currency_code}")
    if currency is None and ctx.supplier is not None:
        # CAT-1: строка без валюты — валюта цен поставщика из его карточки.
        currency = getattr(ctx.supplier, "default_currency", None)

    stock_code = _cell(row, columns["stock"]).upper()
    stock = ctx.stock.get(stock_code) if stock_code else None
    if stock_code and not stock:
        raise ValueError(f"UNKNOWN_STOCK_STATUS:{stock_code}")

    return currency, stock, _parse_decimal(_cell(row, columns["price"]))


def _process_one_row(ctx: _Ctx, row, columns: dict):
    """Handle a single row. Returns an outcome dict, or None for a blank row.

    Raises ValueError with a stable code for row-level problems so the caller
    can roll back this row's savepoint and report it.
    """
    name = _cell(row, columns["name"])
    if not name:
        return None

    currency, stock, price = _row_commercials(ctx, row, columns)
    taxonomy, warnings = _row_taxonomy(ctx, row, columns)
    valid_from, valid_until = _row_validity(ctx, row, columns)
    supplier_sku = _cell(row, columns["supplier_sku"])

    product, created, proposals = _apply_product(
        ctx,
        {
            "name": name,
            "description": _cell(row, columns["description"]),
            "brand_name": _cell(row, columns["brand"]),
            "mpn": _cell(row, columns["mpn"]),
            "gost": _cell(row, columns["gost"]),
            "uom_code": _cell(row, columns["uom"]).lower(),
            **taxonomy,
        },
        supplier_sku,
    )

    offer_written = None  # None — без предложения, True — новое, False — обновлённая цена
    if ctx.supplier and price is not None:
        offer_written = _upsert_offer(
            ctx,
            product,
            {
                "price": price,
                "currency": currency,
                "stock": stock,
                "supplier_sku": supplier_sku,
                "lead": _cell(row, columns["lead"]),
                "moq": _parse_int(_cell(row, columns["moq"]), 1),
                "valid_from": valid_from,
                "valid_until": valid_until,
                "item_name": name,
                "brand": _cell(row, columns["brand"]),
                "mpn": _cell(row, columns["mpn"]),
            },
        )

    return {
        "created": created,
        "offer": offer_written,
        "product": product,
        "warnings": warnings,
        "proposals": proposals,
    }


def _domain_keys(domains) -> dict:
    """Направление и по коду (`GENERAL_GOODS`), и по человеческому названию — регистр не важен.

    Название кладём первым, код — вторым: при совпадении выигрывает КОД, он однозначен.
    """
    by_key = {domain.name.lower(): domain for domain in domains if domain.name}
    by_key.update({domain.code.lower(): domain for domain in domains})
    return by_key


def _build_context(supplier, dry_run: bool, hs_status: dict = None, **extra) -> _Ctx:
    from catalog.models import (
        Category,
        DomainType,
        Manufacturer,
        Product,
        ProductFieldProposal,
        ProductStatus,
        StockStatus,
        SupplierOffer,
    )
    from master_data.models import Currency, UnitOfMeasure

    domains = list(DomainType.objects.all())
    return _Ctx(
        supplier=supplier,
        Product=Product,
        Manufacturer=Manufacturer,
        SupplierOffer=SupplierOffer,
        uom={u.code.lower(): u for u in UnitOfMeasure.objects.all()},
        currency={c.code.upper(): c for c in Currency.objects.all()},
        stock={s.code.upper(): s for s in StockStatus.objects.all()},
        domain={d.code: d for d in domains},
        domain_by_key=_domain_keys(domains),
        # Только ДЕЙСТВУЮЩИЕ категории: выключенная ветка таксономии — не цель для новых карточек.
        # `order_by` фиксирует победителя при одинаковых названиях в разных ветках дерева.
        category_by_name={
            category.name.strip().lower(): category
            for category in Category.objects.filter(is_active=True).order_by("-sort_order", "-id")
        },
        hs_status=hs_status or {},
        hs_code_max_length=Product._meta.get_field("hs_code").max_length,
        status_draft=ProductStatus.objects.filter(code="DRAFT").first(),
        brand_cache={},
        touched_products={},
        dry_run=dry_run,
        Proposal=ProductFieldProposal,
        **extra,
    )


def _iterate_rows(ctx: _Ctx, data_frame, columns: dict, result: ImportResult, progress_callback) -> None:
    total = len(data_frame)
    for index, row in data_frame.iterrows():
        row_number = index + 2  # +1 for header, +1 for 1-based display
        try:
            with transaction.atomic():
                outcome = _process_one_row(ctx, row, columns)
        except ValueError as exc:
            result.add_error(row_number, str(exc))
            continue
        except Exception:  # noqa: BLE001 — isolate one row, keep importing
            logger.exception("Catalog import row %s failed", row_number)
            result.add_error(row_number, "ROW_FAILED")
            continue

        if outcome is None:
            continue
        if outcome["created"]:
            result.created += 1
        else:
            result.updated += 1
        if outcome["offer"] is not None:
            result.offers_upserted += 1
            if outcome["offer"]:
                result.offers_created += 1
            else:
                result.offers_updated += 1
        for proposal in outcome["proposals"]:
            result.add_proposal(row_number, proposal)
        # Предупреждения записываются ТОЛЬКО после успеха строки: у откатанной строки их нет.
        for message in outcome["warnings"]:
            result.add_warning(row_number, message)
        if not _hidden_from_contact(ctx, outcome["product"]):
            # Полноту чужой неопубликованной карточки в отчёт партнёра не считаем (PART-2)
            ctx.touched_products[outcome["product"].pk] = outcome["product"]

        processed = result.created + result.updated + result.skipped
        if progress_callback and processed % 500 == 0:
            progress_callback(processed, total)


def _count_file_rows(file_content: bytes) -> int:
    """Сколько СОДЕРЖАТЕЛЬНЫХ строк данных в первом листе (без строки заголовка).

    Считаем потоком (`read_only=True` у openpyxl отдаёт строки по одной и не поднимает лист
    в память целиком) и только когда файл заведомо длиннее предела: платить за второй проход
    ради числа «сколько отрезано» имеет смысл лишь тогда, когда отрезать действительно есть что.
    """
    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(file_content), read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        filled = sum(
            1
            for cells in sheet.iter_rows(values_only=True)
            if any(cell is not None and str(cell).strip() for cell in cells)
        )
    finally:
        workbook.close()
    return max(0, filled - 1)  # первая содержательная строка — заголовок


def _read_rows(file_content: bytes):
    """`(DataFrame, сколько строк файла не попало в разбор)`.

    `nrows=MAX_EXCEL_ROWS` раньше отрезал хвост МОЛЧА: продавец видел «создано 50 000» и не
    узнавал, что остальные строки его прайса система просто не читала. Читаем на одну строку
    больше предела — лишняя строка и есть признак переполнения.

    `dtype=str` — НЕ косметика. Без него pandas выводит тип колонки сам, и колонка кодов ТН ВЭД
    из текстовой становится числовой: `0101210000` превращается в `101210000`, теряя ведущий
    ноль. Продавец получал замечание «кода нет в справочнике» на совершенно верный код, а в
    карточку писался испорченный — при том что нули начинают целые группы классификатора
    (01–09). Ловится только глазами: файл разбирается «успешно», просто цифра пропадает.
    Ячейки и так разбираются нашими парсерами из строк, поэтому чтение всего как текста ничего
    больше не меняет.
    """
    data_frame = pd.read_excel(BytesIO(file_content), nrows=MAX_EXCEL_ROWS + 1, dtype=str)
    if len(data_frame) <= MAX_EXCEL_ROWS:
        return data_frame, 0
    return data_frame.head(MAX_EXCEL_ROWS), max(0, _count_file_rows(file_content) - MAX_EXCEL_ROWS)


def _prescan_hs_codes(data_frame, columns: dict) -> dict:
    """Вердикт классификатора по ВСЕМ кодам файла — два запроса на импорт вместо двух на строку."""
    column = columns.get("hs_code")
    if not column:
        return {}

    from catalog.hs_suggest import validate_hs_codes

    values = data_frame[column]
    if getattr(values, "ndim", 1) > 1:  # два заголовка совпали после нормализации регистра
        values = values.iloc[:, 0]
    codes = {_hs_digits(str(value)) for value in values.tolist()}
    return validate_hs_codes(codes)


def _summarize_publishability(ctx: _Ctx, result: ImportResult) -> None:
    """Дописать в отчёт, сколько карточек НЕ пройдут порог публикации и чего им не хватает."""
    from catalog.completeness import summarize_completeness

    summary = summarize_completeness(ctx.touched_products.values())
    result.unpublishable = summary["unpublishable"]
    result.missing_breakdown = summary["missing_breakdown"]


def run_catalog_import_frame(
    data_frame,
    supplier_company_id=None,
    dry_run=False,
    progress_callback=None,
    *,
    actor_id=None,
    contact_id=None,
    valid_from=None,
    valid_until=None,
    owner_company_id=None,
) -> dict:
    """Ядро импорта: DataFrame строк → upsert PIM-карточек + офферов загрузившего.

    Выделено из байтовой версии (R5b), чтобы ИИ-путь (`services_ai_catalog` собирает строки из
    PDF/фото/произвольного файла) проходил через ТОТ ЖЕ разбор шапки, те же справочники и тот же
    отчёт, а не через параллельный движок. Заголовки колонок нормализуются здесь же, поэтому на
    вход годится и DataFrame прямо из файла, и DataFrame из словарей с русскими заголовками
    шаблона. Returns a structured result dict (see ImportResult.as_dict). Raises
    ValueError('NAME_COLUMN_NOT_FOUND') when the frame has no recognizable name
    column — the only fatal, file-level error.
    """
    from accounts.models import Company

    supplier = (
        Company.objects.select_related("default_currency").filter(id=supplier_company_id).first()
        if supplier_company_id
        else None
    )

    data_frame.columns = [str(column).lower().strip() for column in data_frame.columns]
    columns = _resolve_columns(list(data_frame.columns))
    if not columns["name"]:
        raise ValueError("NAME_COLUMN_NOT_FOUND")

    ctx = _build_context(
        supplier,
        dry_run,
        hs_status=_prescan_hs_codes(data_frame, columns),
        actor=_actor(actor_id),
        contact=_contact(contact_id),
        owner=Company.objects.filter(id=owner_company_id).first() if owner_company_id else supplier,
        valid_from=_as_date(valid_from),
        valid_until=_as_date(valid_until),
    )
    result = ImportResult(dry_run=dry_run)

    if dry_run:
        with transaction.atomic():
            _iterate_rows(ctx, data_frame, columns, result, progress_callback)
            # Сводка считается ВНУТРИ транзакции: карточки предпросмотра живут только в ней.
            _summarize_publishability(ctx, result)
            transaction.set_rollback(True)
    else:
        # История цены (pghistory, CAT-1): кто загрузил и откуда цена — в контексте каждого снимка предложения.
        # PART-2: загрузка из кабинета — автор контакт (`contact`), пользователя ERP нет.
        extra = {"contact": contact_id} if contact_id else {}
        with pghistory.context(user=actor_id, source="price_list", **extra):
            _iterate_rows(ctx, data_frame, columns, result, progress_callback)
        _summarize_publishability(ctx, result)

    return result.as_dict()


def _actor(actor_id):
    if not actor_id:
        return None
    from accounts.models import CustomUser

    return CustomUser.objects.filter(pk=actor_id).first()


def _contact(contact_id):
    if not contact_id:
        return None
    from parties.models import Contact

    return Contact.objects.filter(pk=contact_id).first()


def _as_date(value):
    """Срок на весь файл: дата или строка `ГГГГ-ММ-ДД` (задача Celery получает его JSON-строкой)."""
    if value in (None, ""):
        return None
    if hasattr(value, "year"):
        return value
    return _parse_date(str(value))


def run_catalog_import(
    file_content: bytes,
    supplier_company_id=None,
    dry_run=False,
    progress_callback=None,
    **options,
) -> dict:
    """Parse an .xlsx and upsert PIM products + the uploader's offers.

    Тонкая байтовая обёртка над `run_catalog_import_frame`: читает файл (с пределом строк) и
    дописывает в отчёт `rows_truncated` — единственное, что знает только файловый слой.
    """
    data_frame, rows_truncated = _read_rows(file_content)
    result = run_catalog_import_frame(
        data_frame,
        supplier_company_id=supplier_company_id,
        dry_run=dry_run,
        progress_callback=progress_callback,
        **options,
    )
    result["rows_truncated"] = rows_truncated
    return result
