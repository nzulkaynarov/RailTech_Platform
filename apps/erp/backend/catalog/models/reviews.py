"""Проверка карточки партнёра (PART-2, ADR-0022 п. 4): история отправок и решений.

Карточкой владеем мы, партнёр — источник данных. Партнёр отправляет черновик или возвращённую карточку «на проверку» —
строка со статусом «ждёт решения»; сотрудник каталога публикует её или возвращает с причиной (очередь проверки — PART-3).
Строки не удаляются: по ним партнёр видит, что и когда решили, а сотрудник — кто отправлял. Открытая проверка у карточки
не больше одной (повторная отправка ничего не дублирует).

Эталоны: Ozon Seller и Wildberries (карточка «на модерации» → «создана» / «с ошибками» и причина по полям), SAP Ariba
(загрузка каталога → одобрение покупателем).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

#: Поля карточки, к которым сотрудник привязывает замечание при возврате (партнёр видит подсветку поля). `other` — замечание
#: не к одному полю. Перечень — `PartnerIssueField` контракта портала.
ISSUE_FIELDS = (
    "name",
    "description",
    "brand",
    "manufacturer_part_number",
    "gost_drawing",
    "category",
    "uom",
    "hs_code",
    "price",
    "valid_until",
    "other",
)
MAX_ISSUES = 30
MAX_ISSUE_COMMENT = 500


def clean_issues(raw) -> list[dict]:
    """Замечания возврата → `[{field, comment}]`; неверная форма — `ValueError` с кодом (очередь проверки, PART-3, берёт отсюда).

    Поле — из `ISSUE_FIELDS`, комментарий — непустой текст до 500 знаков, замечаний не больше 30; повтор поля с тем же текстом
    отбрасывается.
    """
    if raw in (None, ""):
        return []
    if not isinstance(raw, (list, tuple)) or len(raw) > MAX_ISSUES:
        raise ValueError("REVIEW_ISSUES_INVALID")
    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("REVIEW_ISSUES_INVALID")
        field, comment = item.get("field"), str(item.get("comment") or "").strip()
        if field not in ISSUE_FIELDS or not comment or len(comment) > MAX_ISSUE_COMMENT:
            raise ValueError("REVIEW_ISSUES_INVALID")
        entry = {"field": field, "comment": comment}
        if entry not in cleaned:
            cleaned.append(entry)
    return cleaned


class ProductReview(models.Model):
    class Decision(models.TextChoices):
        PENDING = "pending", _("Ждёт решения")
        PUBLISHED = "published", _("Опубликована")
        RETURNED = "returned", _("Возвращена")
        #: Проверка закрыта без решения: карточку сняли с публикации, архивировали или отправили заново (висящая проверка).
        CANCELLED = "cancelled", _("Снята с проверки")

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="reviews",
        verbose_name=_("Карточка"),
    )
    submitted_by_contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто отправил (контакт кабинета)"),
    )
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Когда отправлена"))
    decision = models.CharField(
        max_length=16,
        choices=Decision.choices,
        default=Decision.PENDING,
        db_index=True,
        verbose_name=_("Решение"),
    )
    reason = models.TextField(blank=True, default="", verbose_name=_("Причина возврата (общий комментарий)"))
    #: Замечания по полям: `[{field, comment}]` (`clean_issues`). Партнёр видит их подсветкой поля рядом с общей причиной.
    field_issues = models.JSONField(default=list, blank=True, verbose_name=_("Замечания по полям"))
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто решил"),
    )
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Когда решено"))

    class Meta:
        verbose_name = _("Проверка карточки")
        verbose_name_plural = _("Каталог: проверки карточек")
        ordering = ["-submitted_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(decision="pending"),
                name="catalog_one_pending_review",
            ),
            # Возврат без причины партнёру нечего исправлять.
            models.CheckConstraint(
                condition=~Q(decision="returned") | ~Q(reason=""),
                name="catalog_returned_review_has_reason",
            ),
        ]

    def __str__(self):
        return f"{self.product_id}: {self.decision}"
