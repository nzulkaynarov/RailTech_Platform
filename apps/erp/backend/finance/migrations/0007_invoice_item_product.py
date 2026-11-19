"""ADR-0027 п. 1 и 10: строка счёта ссылается на карточку каталога и несёт единицу строки КП.

Перенос данных повторяет `crm.services.manual_invoice._resolve_cards` на исторических моделях: строка из КП берёт
карточку и единицу своей строки КП; ручная строка (только текст) — карточку нашей компании с тем же названием или
новый черновик. Владелец карточки — `OWN_COMPANY_ID`; без него ручная строка не трогается. Откат схемы убирает поля
вместе со связью; созданные черновики остаются в очереди «Новые из заявок» — их можно слить или удалить там.
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def forwards(apps, schema_editor):
    InvoiceItem = apps.get_model("finance", "InvoiceItem")
    Product = apps.get_model("catalog", "Product")
    ProductStatus = apps.get_model("catalog", "ProductStatus")
    DomainType = apps.get_model("catalog", "DomainType")

    for item in InvoiceItem.objects.filter(product__isnull=True, source_quote_item__isnull=False).select_related(
        "source_quote_item"
    ):
        qi = item.source_quote_item
        item.product_id = qi.product_id
        item.unit = qi.unit or ""
        item.unit_code = qi.unit_code or ""
        item.save(update_fields=["product", "unit", "unit_code"])

    own = getattr(settings, "OWN_COMPANY_ID", None)
    manual = list(
        InvoiceItem.objects.filter(product__isnull=True, source_quote_item__isnull=True).select_related("invoice")
    )
    if not own or not manual:
        return
    owner_id = int(own)
    draft = ProductStatus.objects.filter(code="DRAFT").first()
    goods = DomainType.objects.filter(code="GENERAL_GOODS").first()
    mine = Product.objects.filter(owner_company_id=owner_id)
    for item in manual:
        title = (item.description or "").strip()
        if not title:
            continue
        product = mine.filter(name__iexact=title).first()
        if product is not None:
            product.demand_count = (product.demand_count or 0) + 1
            product.save(update_fields=["demand_count"])
        else:
            prefix = getattr(goods, "sku_prefix", "") or "RT"
            product = Product.objects.create(
                name=title[:255],
                sku=f"{prefix}-{uuid.uuid4().hex[:8].upper()}",
                owner_company_id=owner_id,
                status=draft,
                domain_type=goods,
                source_deal_id=item.invoice.deal_id,
                demand_count=1,
            )
        item.product = product
        item.save(update_fields=["product"])


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0006_decimal_quantity"),
        ("catalog", "0017_brand_names"),
        ("sales", "0019_decimal_quote_quantity"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoiceitem",
            name="product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="invoice_items",
                to="catalog.product",
                verbose_name="Карточка каталога",
            ),
        ),
        migrations.AddField(
            model_name="invoiceitem",
            name="unit",
            field=models.CharField(blank=True, default="", max_length=32, verbose_name="Единица измерения"),
        ),
        migrations.AddField(
            model_name="invoiceitem",
            name="unit_code",
            field=models.CharField(
                blank=True, default="", max_length=8, verbose_name="Код ед. изм. (UN/ECE Rec 20)"
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
