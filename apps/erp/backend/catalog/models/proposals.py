"""Предложение поставщика по полю чужой карточки (CAT-1): расхождение из прайса ждёт одобрения человеком.

Два завода продают одну деталь (бренд + артикул производителя) — карточка одна, у каждого своё предложение. Прайс завода Б
не переписывает наименование, категорию и ТН ВЭД карточки, которую завёл завод А или которая уже опубликована: каждое
расхождение становится строкой здесь, сотрудник каталога принимает её или отклоняет (`catalog/desk/proposals.py`).

Эталоны: SAP Ariba catalog upload (загрузка → сопоставление → одобрение изменений), Akeneo «proposals» (поставщик
предлагает правку мастер-записи, владелец каталога принимает). Одна открытая строка на (карточка, поле, поставщик):
повторная загрузка того же файла её не дублирует, новое значение обновляет её; отклонённое значение больше не предлагается.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class ProductFieldProposal(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("На одобрении")
        ACCEPTED = "accepted", _("Принято")
        REJECTED = "rejected", _("Отклонено")

    class Field(models.TextChoices):
        NAME = "name", _("Наименование")
        DESCRIPTION = "description", _("Описание")
        CATEGORY = "category", _("Категория")
        HS_CODE = "hs_code", _("Код ТН ВЭД")
        UOM = "uom", _("Единица измерения")
        DOMAIN = "domain_type", _("Направление")
        GOST = "gost_drawing", _("ГОСТ / чертёж")

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="field_proposals",
        verbose_name=_("Карточка"),
    )
    field = models.CharField(max_length=32, choices=Field.choices, verbose_name=_("Поле"))
    current_value = models.TextField(blank=True, default="", verbose_name=_("Было в карточке"))
    proposed_value = models.TextField(verbose_name=_("Предложено"))
    #: Id записи справочника для полей-ссылок (категория, единица, направление); у текстовых полей пусто.
    proposed_ref = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Id значения справочника"))
    supplier = models.ForeignKey(
        "parties.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_field_proposals",
        verbose_name=_("Поставщик"),
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True, verbose_name=_("Статус")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто загрузил"),
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто решил"),
    )
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Когда решено"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Предложение по полю карточки")
        verbose_name_plural = _("Каталог: предложения по полям карточек")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "field", "supplier"],
                condition=Q(status="pending"),
                nulls_distinct=False,
                name="catalog_one_open_field_proposal",
            )
        ]

    def __str__(self):
        return f"{self.product_id}.{self.field}: {self.proposed_value[:40]}"
