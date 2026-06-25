from collections import defaultdict

from django.db import migrations


def route_existing(apps, schema_editor):
    """Back-fill DealSellerRouting so no deal disappears from the current seller's
    pipeline when the see-all queryset is replaced by routing-scoped access.

    Per deal, in priority order:
      1) route to every distinct owner_company of the deal's quote-item products;
      2) else (product-less / free-text deal) route to the lone SUPPLIER company
         if exactly one exists (the single-seller assumption that holds today).
    """
    Deal = apps.get_model("crm", "Deal")
    DealSellerRouting = apps.get_model("crm", "DealSellerRouting")
    QuoteItem = apps.get_model("crm", "QuoteItem")
    Company = apps.get_model("accounts", "Company")

    deal_owner_ids = defaultdict(set)
    for row in QuoteItem.objects.filter(product__owner_company__isnull=False).values(
        "quote__deal_id", "product__owner_company_id"
    ):
        deal_owner_ids[row["quote__deal_id"]].add(row["product__owner_company_id"])

    supplier_ids = list(Company.objects.filter(types__code="SUPPLIER").values_list("id", flat=True).distinct())
    lone_seller_id = supplier_ids[0] if len(supplier_ids) == 1 else None

    routings = []
    for deal_id in Deal.objects.values_list("id", flat=True):
        owner_ids = deal_owner_ids.get(deal_id)
        if not owner_ids and lone_seller_id is not None:
            owner_ids = {lone_seller_id}
        for seller_id in owner_ids or ():
            routings.append(DealSellerRouting(deal_id=deal_id, seller_company_id=seller_id))
    DealSellerRouting.objects.bulk_create(routings, ignore_conflicts=True)


def unroute(apps, schema_editor):
    apps.get_model("crm", "DealSellerRouting").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("crm", "0033_dealsellerrouting_deal_target_sellers_and_more")]
    operations = [migrations.RunPython(route_existing, unroute)]
