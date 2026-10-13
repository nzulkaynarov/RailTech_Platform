"""Заявка продавца на новую категорию — escape-hatch платформенной таксономии (R6, D7).

Почему заявка, а не «продавец заводит свою категорию»:

**Эталон — Google Merchant Center, двухслойная модель.** Таксономия площадки
(`google_product_category`) фиксирована: по ней покупатель навигируется, строятся фасеты и
подбирается код ТН ВЭД. Своё дерево у каждого продавца это разрушило бы. GMC прямо советует:
если подходящей категории нет — обратиться к площадке, а не ломать классификатор.

**Что было до этого.** Страница категорий читала дерево и обещала подписью «Управление
деревом категорий», при этом ни создать, ни переименовать, ни ПОПРОСИТЬ категорию было
нельзя. Продавец, чей товар не ложился ни в одну строку справочника, упирался в стену:
категория обязательна для публикации (`catalog/completeness.py`), а обращения к платформе из
этого места не существовало.

Заявка НЕ является гейтом: карточка заводится, правится и живёт без неё (PRODUCT RULE 2 —
трение убираем, не добавляем). Она лишь превращает тупик в обращение.

Rule 1: одобрение заявки НЕ создаёт категорию автоматически. Оператор заводит строку
справочника сам (страница категорий операторской плоскости) и привязывает её к заявке —
чем закрывает обращение и говорит продавцу, куда класть товар.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class CategoryRequest(models.Model):
    """Обращение продавца: «нужной категории нет — заведите вот такую»."""

    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CHOICES = [
        (STATUS_PENDING, _("На рассмотрении")),
        (STATUS_APPROVED, _("Одобрено")),
        (STATUS_REJECTED, _("Отклонено")),
    ]
    #: Статусы, из которых заявку ещё можно рассмотреть (одобрить или отклонить).
    OPEN_STATUSES = (STATUS_PENDING,)

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="category_requests",
        verbose_name=_("Компания"),
        help_text=_("Компания-продавец, которой не хватило категории"),
    )
    requested_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_requests",
        verbose_name=_("Автор заявки"),
        help_text=_("Пользователь, отправивший обращение"),
    )
    proposed_name = models.CharField(
        max_length=255,
        verbose_name=_("Предлагаемая категория"),
        help_text=_("Название категории, которой не хватает в справочнике"),
    )
    parent = models.ForeignKey(
        "catalog.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_requests",
        verbose_name=_("Предлагаемое место в дереве"),
        help_text=_("Категория, внутри которой продавец ожидает увидеть новую"),
    )
    domain_type = models.ForeignKey(
        "catalog.DomainType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_requests",
        verbose_name=_("Домен каталога"),
        help_text=_("Домен, к которому относится предлагаемая категория"),
    )
    justification = models.TextField(
        blank=True,
        verbose_name=_("Пояснение"),
        help_text=_("Примеры товаров и почему существующие категории не подходят"),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name=_("Статус"),
        help_text=_("Текущий статус рассмотрения обращения"),
    )
    resulting_category = models.ForeignKey(
        "catalog.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fulfilled_requests",
        verbose_name=_("Заведённая категория"),
        help_text=_("Категория справочника, которой оператор закрыл обращение"),
    )
    reviewed_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_category_requests",
        verbose_name=_("Рассмотрел"),
        help_text=_("Оператор платформы, принявший решение"),
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Дата рассмотрения"),
    )
    review_notes = models.TextField(
        blank=True,
        verbose_name=_("Комментарий оператора"),
        help_text=_("Основание решения — обязательно при отказе"),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Дата создания"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Дата обновления"))

    class Meta:
        verbose_name = _("Заявка на категорию")
        verbose_name_plural = _("Заявки на категории")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "status"], name="catreq_company_status_idx"),
        ]

    def __str__(self):
        return f"{self.proposed_name} ({self.status})"
