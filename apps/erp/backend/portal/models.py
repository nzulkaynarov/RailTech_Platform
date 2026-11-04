"""Portal models: сессии портала, magic-links, загрузки и коды акцепта КП."""

import uuid

from django.conf import settings
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
    """Одноразовое письмо входа: ссылка и код (B-MAIL-1) — вход по запросу клиента (60 минут) или приглашение (24 часа).

    Ссылка и 6-значный код — одна запись: погашение любым из двух гасит оба. В базе — только хеши.
    """

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
    code_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("HMAC-SHA256 кода входа"),
        help_text=_("Сырой 6-значный код есть только в письме; пусто — у записи нет кода"),
    )
    code_attempts = models.PositiveSmallIntegerField(default=0, verbose_name=_("Неверных попыток кода"))
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


class QuoteComment(models.Model):
    """Комментарий к КП (SPEC-v3 §8 «КП — принять / отклонить с причиной / комментарий», B-CABFIX-1).

    Клиент пишет из кабинета (`POST /quotes/{id}/comments`, автор — контакт), лента отдаётся в `Quote.comments`.
    Автор-сотрудник (`author_user`) заложен для ответа менеджера из Платформы; пока его пишет только клиент.
    """

    quote = models.ForeignKey(
        "sales.Quote",
        on_delete=models.CASCADE,
        related_name="client_comments",
        verbose_name=_("КП"),
    )
    author_contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quote_comments",
        verbose_name=_("Автор — контакт клиента"),
    )
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quote_comments",
        verbose_name=_("Автор — сотрудник"),
    )
    text = models.TextField(verbose_name=_("Текст"))  # до 2000 знаков — `QuoteCommentCreate.text` контракта
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Комментарий к КП")
        verbose_name_plural = _("Комментарии к КП")
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"QuoteComment(quote={self.quote_id}, {self.created_at:%Y-%m-%d})"


class PortalMessage(models.Model):
    """Лента чата кабинета компании (CHAT-1, ADR-0023): проекция переписки, видят все контакты компании.

    Сообщение контакта пишет портал (`POST /messages`) вместе с событием `erp.cabinet.message_posted` — CRM кладёт его в
    беседу канала `cabinet`; ответ менеджера приходит событием `crm.cabinet.message_sent` (`crm_message_id`). Владелец
    переписки — CRM; стирание ПД человека в CRM стирает только его сообщения (`erased`: текста и автора нет), стирание
    клиента целиком — всю ленту (`crm.lead.erased`, `PortalChatErasure`).
    """

    DIRECTION_CLIENT = "client"
    DIRECTION_MANAGER = "manager"
    CONTEXT_KINDS = ("deal", "quote", "invoice", "act")

    company = models.ForeignKey(
        "parties.Company", on_delete=models.CASCADE, related_name="portal_messages", verbose_name=_("Компания")
    )
    direction = models.CharField(
        max_length=10,
        choices=[(DIRECTION_CLIENT, _("Контакт компании")), (DIRECTION_MANAGER, _("Менеджер"))],
        verbose_name=_("Направление"),
    )
    author_contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portal_messages",
        verbose_name=_("Автор — контакт компании"),
    )
    author_name = models.CharField(max_length=255, blank=True, verbose_name=_("Имя автора"))
    text = models.TextField(verbose_name=_("Текст"))  # до 4000 знаков — `PortalMessageCreate.text` контракта
    context_kind = models.CharField(
        max_length=10, blank=True, choices=[(k, k) for k in CONTEXT_KINDS], verbose_name=_("Метка: вид документа")
    )
    context_id = models.BigIntegerField(null=True, blank=True, verbose_name=_("Метка: id документа"))
    context_number = models.CharField(max_length=64, blank=True, verbose_name=_("Метка: номер документа"))
    client_message_id = models.CharField(max_length=64, null=True, blank=True, verbose_name=_("Ключ повтора Cabinet"))
    crm_message_id = models.BigIntegerField(null=True, blank=True, verbose_name=_("Сообщение CRM"))
    #: Автор стёр свои ПД (`crm.lead.erased`, scope=authors): текста и автора нет, строка ленты остаётся.
    erased = models.BooleanField(default=False, verbose_name=_("Стёрто по запросу автора"))
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = _("Сообщение чата кабинета")
        verbose_name_plural = _("Сообщения чата кабинета")
        ordering = ["id"]
        indexes = [models.Index(fields=["company", "id"], name="portal_msg_company_id")]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "client_message_id"],
                condition=models.Q(client_message_id__isnull=False),
                name="uq_portal_msg_client_key",
            ),
            models.UniqueConstraint(
                fields=["crm_message_id"],
                condition=models.Q(crm_message_id__isnull=False),
                name="uq_portal_msg_crm_id",
            ),
        ]

    def __str__(self):
        return f"PortalMessage(company={self.company_id}, {self.direction}, #{self.pk})"


class PortalChatReader(models.Model):
    """Прочитанность и присутствие контакта в чате кабинета: `last_read_id` — до какого сообщения прочитано (бейдж
    `Me.unread`), `last_seen_at` — когда контакт последний раз смотрел ленту (опрос, с прореживанием; по нему уведомления
    решают, в кабинете ли контакт сейчас — NOTIFY-2)."""

    company = models.ForeignKey("parties.Company", on_delete=models.CASCADE, related_name="+")
    contact = models.ForeignKey("parties.Contact", on_delete=models.CASCADE, related_name="portal_chat_readers")
    last_read_id = models.BigIntegerField(default=0, verbose_name=_("Прочитано до сообщения"))
    last_seen_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Последний раз в чате"))

    class Meta:
        verbose_name = _("Читатель чата кабинета")
        verbose_name_plural = _("Читатели чата кабинета")
        constraints = [models.UniqueConstraint(fields=["company", "contact"], name="uq_portal_chat_reader")]


class PortalChatErasure(models.Model):
    """Лента компании стёрта по `crm.lead.erased` (ПД клиента): ответ менеджера, отправленный не позже `erased_at`,
    пришедший с опозданием, ленту не восстанавливает."""

    company = models.OneToOneField(
        "parties.Company", on_delete=models.CASCADE, related_name="portal_chat_erasure", verbose_name=_("Компания")
    )
    erased_at = models.DateTimeField(verbose_name=_("Стёрто в CRM"))

    class Meta:
        verbose_name = _("Стирание чата кабинета")
        verbose_name_plural = _("Стирания чата кабинета")
