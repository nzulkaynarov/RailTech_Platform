"""ADR-0027: каждая строка КП без карточки получает карточку каталога — найденную или черновик.

Логика повторяет `catalog.candidates.link_quote_lines` на исторических моделях: живые модели в миграции ломаются, как
только схема уйдёт вперёд. Владелец карточки — `OWN_COMPANY_ID`, иначе продавец КП; без владельца строка не трогается.
Откат снимает связь строк с черновиками, созданными из своей же сделки со спросом 1, и удаляет такие черновики.
"""

import uuid

from django.conf import settings
from django.db import migrations


def _title(item) -> str:
    for value in (item.name_canonical, item.imported_raw_name, item.mpn, item.gost_drawing):
        value = (value or "").strip()
        if value:
            return value
    return ""


def forwards(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    ProductStatus = apps.get_model("catalog", "ProductStatus")
    DomainType = apps.get_model("catalog", "DomainType")
    QuoteItem = apps.get_model("sales", "QuoteItem")
    CalcLine = apps.get_model("sales", "CalcLine")

    items = list(QuoteItem.objects.filter(product__isnull=True, display_type="ITEM").select_related("quote"))
    if not items:
        return
    draft = ProductStatus.objects.filter(code="DRAFT").first()
    goods = DomainType.objects.filter(code="GENERAL_GOODS").first()
    services = DomainType.objects.filter(code="SERVICES").first()
    kinds = dict(CalcLine.objects.filter(item_id__in=[i.id for i in items]).values_list("item_id", "kind"))
    own = getattr(settings, "OWN_COMPANY_ID", None)

    for item in items:
        owner_id = int(own) if own else item.quote.seller_company_id
        title = _title(item)
        if not owner_id or not title:
            continue
        mine = Product.objects.filter(owner_company_id=owner_id)
        product = None
        mpn = (item.mpn or "").strip()
        gost = (item.gost_drawing or "").strip()
        if mpn:
            product = mine.filter(manufacturer_part_number__iexact=mpn).first()
        if product is None and gost:
            product = mine.filter(gost_drawing__iexact=gost).first()
        if product is None:
            product = mine.filter(name__iexact=title).first()
        if product is not None:
            product.demand_count = (product.demand_count or 0) + 1
            product.save(update_fields=["demand_count"])
        else:
            domain = services if kinds.get(item.id) == "service" else goods
            prefix = getattr(domain, "sku_prefix", "") or "RT"
            product = Product.objects.create(
                name=title[:255],
                sku=f"{prefix}-{uuid.uuid4().hex[:8].upper()}",
                owner_company_id=owner_id,
                status=draft,
                domain_type=domain,
                source_deal_id=item.quote.deal_id,
                demand_count=1,
                manufacturer_part_number=mpn,
                gost_drawing=gost,
            )
        item.product = product
        item.save(update_fields=["product"])


def backwards(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    QuoteItem = apps.get_model("sales", "QuoteItem")
    # Сравнение по id: модели двух приложений в историческом состоянии — разные классы, `product__in=QuerySet` не проходит.
    drafts = dict(
        Product.objects.filter(status__code="DRAFT", demand_count__lte=1, source_deal__isnull=False).values_list(
            "pk", "source_deal_id"
        )
    )
    ids = set()
    for item in QuoteItem.objects.filter(product_id__in=list(drafts)).select_related("quote"):
        if drafts[item.product_id] == item.quote.deal_id:
            ids.add(item.product_id)
            item.product_id = None
            item.save(update_fields=["product"])
    used = set(QuoteItem.objects.filter(product_id__in=ids).values_list("product_id", flat=True))
    Product.objects.filter(pk__in=ids - used).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0015_categories_manufacturers_names"),
        ("sales", "0017_quote_payment_terms"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
