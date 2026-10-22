"""Portal models: сессии портала, magic-links, загрузки и коды акцепта КП."""

import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.storage import get_private_storage


class PortalSession(models.Model):
    """Изолированная сессия клиента в портале (Cabinet → ERP).

    Не пересекается с сессиями сотрудников бэк-офиса (CustomUser).
    Связана с Contact и Company клиента.
    """

    token_hash = models.CharField(
        max_length=64,
        unique=True,
        verbose_name=_("SHA-256 токена сессии"),
        help_text=_("Сырой токен хранится только в cookie клиента"),
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
    """Одноразовый токен для входа по email: вход по запросу клиента (15 минут) или приглашение (24 часа)."""

    PURPOSE_LOGIN = "login"
    PURPOSE_INVITE = "invite"

    token_hash = models.CharField(
        max_length=64,
        unique=True,
        verbose_name=_("SHA-256 токена ссылки"),
        help_text=_("Сырой токен есть только в письме"),
    )
    purpose = models.CharField(
        max_length=10,
        choices=[(PURPOSE_LOGIN, _("Вход по запросу клиента")), (PURPOSE_INVITE, _("Приглашение из ERP"))],
        default=PURPOSE_LOGIN,
        verbose_name=_("Назначение"),
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
        storage=get_private_storage,
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
        max_length=1000,  # `RequestLineIn.text` контракта — до 1000 знаков (FIX-23)
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


class PortalRequestSummary(models.Model):
    """Суть запроса клиента как он её написал (до 5000 знаков по контракту, FIX-21).

    `Deal.title` — 255 знаков и живёт в списках сотрудников, поэтому в нём — сжатая первая строка, а полный текст
    клиента хранится здесь и отдаётся как `ClientRequest.summary`. У сделок без такой записи (передача из CRM,
    сотрудник ERP) суть — название сделки.
    """

    deal = models.OneToOneField(
        "sales.Deal",
        on_delete=models.CASCADE,
        related_name="portal_summary",
        verbose_name=_("Сделка"),
    )
    text = models.TextField(verbose_name=_("Суть запроса"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Суть запроса портала")
        verbose_name_plural = _("Сути запросов портала")

    def __str__(self):
        return f"PortalRequestSummary(deal={self.deal_id})"
