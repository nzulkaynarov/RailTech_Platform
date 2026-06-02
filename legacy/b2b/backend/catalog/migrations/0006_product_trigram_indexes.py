"""Enable pg_trgm and add GIN trigram indexes for Smart Match.

sourcing.services.smart_match_product runs TrigramSimilarity() on Product.name
and Product.gost_drawing. Without the pg_trgm extension and GIN trigram indexes
those queries fall back to a sequential scan, which does not scale to enterprise
catalogs (up to 50k rows per CLAUDE.md). This migration provisions both.
"""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0005_alter_category_domain_type_alter_category_icon_and_more"),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name="product",
            index=GinIndex(name="product_name_trgm_idx", fields=["name"], opclasses=["gin_trgm_ops"]),
        ),
        migrations.AddIndex(
            model_name="product",
            index=GinIndex(name="product_gost_trgm_idx", fields=["gost_drawing"], opclasses=["gin_trgm_ops"]),
        ),
    ]
