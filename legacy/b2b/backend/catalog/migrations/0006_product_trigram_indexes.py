"""Enable pg_trgm and add GIN trigram indexes for Smart Match.

sourcing.services.smart_match_product runs TrigramSimilarity() on Product.name
and Product.gost_drawing. Without the pg_trgm extension and GIN trigram indexes
those queries fall back to a sequential scan, which does not scale to enterprise
catalogs (up to 50k rows per CLAUDE.md).

The indexes are created with raw SQL and deliberately NOT registered in model
state. The test suite runs with --nomigrations (see pyproject.toml), building the
schema straight from the models; declaring a gin_trgm_ops index on the model would
then fail because this extension-creating migration never runs in that path.
"""

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0005_alter_category_domain_type_alter_category_icon_and_more"),
    ]

    operations = [
        TrigramExtension(),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS product_name_trgm_idx "
                "ON catalog_product USING gin (name gin_trgm_ops);"
            ),
            reverse_sql="DROP INDEX IF EXISTS product_name_trgm_idx;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS product_gost_trgm_idx "
                "ON catalog_product USING gin (gost_drawing gin_trgm_ops);"
            ),
            reverse_sql="DROP INDEX IF EXISTS product_gost_trgm_idx;",
        ),
    ]
