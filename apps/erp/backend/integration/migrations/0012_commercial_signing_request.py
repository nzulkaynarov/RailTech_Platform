import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("integration", "0011_partner_crm_link"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommercialSigningRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=16)),
                ("object_id", models.BigIntegerField()),
                ("number", models.CharField(max_length=64)),
                (
                    "fingerprint",
                    models.CharField(help_text="Отпечаток редакции документа на момент запроса", max_length=64),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "На подписи"),
                            ("signed", "Подписан"),
                            ("rejected", "Отказ"),
                            ("stale", "Документ изменён"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("comment", models.TextField(blank=True, default="")),
                ("signer_name", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [models.Index(fields=["kind", "object_id"], name="integration_kind_obj_idx")],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("status", "pending")),
                        fields=("kind", "object_id"),
                        name="uq_commercial_signing_one_pending",
                    )
                ],
            },
        ),
    ]
