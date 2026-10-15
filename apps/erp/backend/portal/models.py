"""Portal models: сессии портала, magic-links, загрузки и коды акцепта КП."""

import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PortalSession(models.Model):
    """Изолированная сессия клиента в портале (Cabinet → ERP).

    Не пересекается с сессиями сотрудников бэк-офиса (CustomUser).
    Связана с Contact и Company клиента.
    """

    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name=_("Токен сессии"),
    )
    contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.CASCADE,
        related_name="portal_sessions",
        verbose_name=_("Контакт клиента"),
    )
    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="portal_sessions",
        verbose_name=_("Компания клиента"),
    )
    auth_method = models.CharField(
        max_length=20,
        choices=[("telegram", "Telegram"), ("magic_link", "Magic Link")],
        verbose_name=_("Способ входа"),
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP адрес"),
    )
    user_agent = models.TextField(
        blank=True,
        verbose_name=_("User Agent"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Сессия портала")
        verbose_name_plural = _("Сессии портала")
        ordering = ["-created_at"]

    def is_valid(self) -> bool:
        return timezone.now() < self.expires_at

    def __str__(self):
        return f"PortalSession({self.contact.email or self.contact.name}, {self.company.name})"


class MagicLinkToken(models.Model):
    """Одноразовый токен для входа по email (15 минут)."""

    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name=_("Токен ссылки"),
    )
    contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.CASCADE,
        related_name="magic_links",
        verbose_name=_("Контакт клиента"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Magic Link токен")
        verbose_name_plural = _("Magic Link токены")
        ordering = ["-created_at"]

    def is_valid(self) -> bool:
        return self.used_at is None and timezone.now() < self.expires_at

    def __str__(self):
        return f"MagicLinkToken({self.contact.email}, valid={self.is_valid()})"


class PortalUpload(models.Model):
    """Временный или постоянный загруженный файл из Cabinet (Q-14)."""

    upload_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        verbose_name=_("ID загрузки"),
    )
    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="portal_uploads",
        verbose_name=_("Компания клиента"),
    )
    uploaded_by = models.ForeignKey(
        "parties.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portal_uploads",
        verbose_name=_("Кем загружен"),
    )
    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="portal_uploads",
        verbose_name=_("Заявка"),
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("Имя файла"),
    )
    file = models.FileField(
        upload_to="portal_uploads/%Y/%m/",
        verbose_name=_("Файл"),
    )
    size_bytes = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Размер в байтах"),
    )
    content_type = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("MIME тип"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Загрузка портала")
        verbose_name_plural = _("Загрузки портала")
        ordering = ["-created_at"]

    def __str__(self):
        return f"PortalUpload({self.name}, {self.company.name})"


class PortalRequestLine(models.Model):
    """Строка спецификации клиентского запроса (Q-16)."""

    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.CASCADE,
        related_name="portal_lines",
        verbose_name=_("Сделка"),
    )
    text = models.CharField(
        max_length=500,
        verbose_name=_("Наименование/описание"),
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name=_("Количество"),
    )
    unit = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Единица измерения"),
    )
    sort_order = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Порядок сортировки"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Строка запроса портала")
        verbose_name_plural = _("Строки запроса портала")
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"PortalRequestLine(deal={self.deal_id}, {self.text})"
