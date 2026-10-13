import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_alter_companyroleapplication_contract_file_and_more"),
        ("master_data", "0002_alter_country_alpha2_alter_country_code_and_more"),
        ("catalog", "0006_product_trigram_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="Manufacturer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "name",
                    models.CharField(
                        help_text="Название бренда/производителя (OEM)",
                        max_length=255,
                        unique=True,
                        verbose_name="Название",
                    ),
                ),
                (
                    "website",
                    models.URLField(
                        blank=True,
                        help_text="Официальный сайт производителя",
                        verbose_name="Сайт",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Неактивные бренды скрыты в формах выбора",
                        verbose_name="Активен",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Дата обновления")),
                (
                    "company",
                    models.ForeignKey(
                        blank=True,
                        help_text="Платформенная компания, если производитель зарегистрирован (местный)",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="manufacturer_brands",
                        to="accounts.company",
                        verbose_name="Связанная компания",
                    ),
                ),
                (
                    "country",
                    models.ForeignKey(
                        blank=True,
                        help_text="Страна происхождения производителя",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="manufacturers",
                        to="master_data.country",
                        verbose_name="Страна",
                    ),
                ),
            ],
            options={
                "verbose_name": "Производитель",
                "verbose_name_plural": "Справочник: Производители",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="product",
            name="brand",
            field=models.ForeignKey(
                blank=True,
                help_text="Бренд/производитель из справочника (OEM). Канонический для PIM.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="products",
                to="catalog.manufacturer",
                verbose_name="Производитель (бренд)",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="manufacturer_part_number",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Заводской артикул. Ключ дедупликации PIM: бренд + артикул.",
                max_length=120,
                verbose_name="Артикул производителя (MPN)",
            ),
        ),
    ]
