from django.db import models
from django.utils.translation import gettext_lazy as _


class AbstractLookup(models.Model):
    """
    DRY-база для всех справочных таблиц.
    Администратор добавляет записи через админку без правки кода.
    """

    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name=_("Код"),
        help_text=_("Уникальный системный код (напр. 'USD', 'FCA', 'IN_STOCK')"),
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("Название"),
        help_text=_("Отображаемое название"),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Порядок сортировки"),
        help_text=_("Порядок отображения в интерфейсе"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен"),
        help_text=_("Неактивные записи скрыты в формах выбора"),
    )

    class Meta:
        abstract = True
        ordering = ["sort_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"
