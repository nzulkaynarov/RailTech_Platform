"""«Документы 2.0» — arbitrary template-based documents (letters, reports, поручения).

Two models:
  * DocumentTemplate — a company's reusable HTML template with `{{placeholder}}`
    tokens (Bitrix24 Document Generator pattern). Company-scoped; a NULL company
    with `is_sample=True` is a global sample template a company can copy to itself.
  * GeneratedDocument — one rendered instance. It stores a SNAPSHOT (`values` +
    `rendered_html`) taken at generation time — it must NOT drift when the source
    deal/quote later changes (Odoo/PandaDoc immutability principle). DRAFT is
    editable + re-renderable; ISSUED is frozen; CANCELLED is terminal.

Placeholder substitution and HTML sanitisation live in
crm/services/document_placeholders.py — the model layer never runs a template
engine on user HTML (SSTI-safe).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import generated_document_pdf_path, get_private_storage


class DocumentTemplate(models.Model):
    """Company template with `{{placeholder}}` tokens, rendered to a GeneratedDocument.

    Scope: `company` = owner. `company IS NULL` + `is_sample=True` = a platform
    sample offered to every company as a «скопировать к себе» starting point.
    """

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="document_templates",
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Компания"),
        help_text=_("Компания-владелец шаблона. Пусто = глобальный образец платформы."),
    )
    name = models.CharField(max_length=255, verbose_name=_("Название"))
    kind = models.ForeignKey(
        "crm.DocumentTemplateKind",
        on_delete=models.PROTECT,
        related_name="templates",
        verbose_name=_("Вид"),
        help_text=_("Письмо / рапорт / произвольный"),
    )
    body_html = models.TextField(
        blank=True,
        default="",
        verbose_name=_("HTML-тело"),
        help_text=_("Санитайзится при сохранении; плейсхолдеры вида {{company.name}}."),
    )
    placeholders_used = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Плейсхолдеры"),
        help_text=_("Производное поле: коды плейсхолдеров, найденные в теле."),
    )
    is_sample = models.BooleanField(
        default=False,
        verbose_name=_("Образец платформы"),
        help_text=_("Глобальный шаблон-заготовка (company пусто) для копирования к себе."),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Активен"))
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_document_templates",
        verbose_name=_("Кем создан"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Дата обновления"))

    class Meta:
        verbose_name = _("Шаблон документа")
        verbose_name_plural = _("Шаблоны документов")
        ordering = ["-is_sample", "name"]
        indexes = [
            models.Index(fields=["company", "is_active"], name="doctpl_company_active_idx"),
            models.Index(fields=["is_sample"], name="doctpl_sample_idx"),
        ]

    def __str__(self):
        scope = self.company.name if self.company_id else "sample"
        return f"[{scope}] {self.name}"


class GeneratedDocument(models.Model):
    """A single rendered document. Immutable snapshot once issued.

    `values` and `rendered_html` are frozen at generation time so the document never
    «плывёт» when the source deal/quote changes afterwards.
    """

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="generated_documents",
        db_index=True,
        verbose_name=_("Компания"),
    )
    deal = models.ForeignKey(
        "crm.Deal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_documents",
        verbose_name=_("Сделка"),
    )
    contact = models.ForeignKey(
        "accounts.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_documents",
        verbose_name=_("Контакт"),
    )
    template = models.ForeignKey(
        "crm.DocumentTemplate",
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("Шаблон"),
    )
    number = models.CharField(max_length=64, unique=True, verbose_name=_("Номер"))
    status = models.ForeignKey(
        "crm.GeneratedDocumentStatus",
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("Статус"),
    )
    title = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Заголовок"))
    values = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Значения плейсхолдеров"),
        help_text=_("Снапшот подставленных значений на момент генерации (НЕ живые ссылки)."),
    )
    rendered_html = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Готовый HTML"),
        help_text=_("Снапшот тела с подставленными значениями."),
    )
    body_html_snapshot = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Снапшот тела шаблона"),
        help_text=_(
            "Копия body_html шаблона на момент генерации. DRAFT ре-рендерится из НЕЁ, "
            "а не из живого template.body_html — иначе поздняя правка шаблона молча меняла бы документ."
        ),
    )
    brand_snapshot = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Снапшот бренд-контекста"),
        help_text=_(
            "Бренд-шапка (лого/реквизиты/accent) на момент ВЫПУСКА. ISSUED-документ рендерится из "
            "неё, поэтому не «плывёт» при поздней правке CompanyDocumentProfile (иммутабельность)."
        ),
    )
    pdf_file = models.FileField(
        upload_to=generated_document_pdf_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("PDF"),
    )
    # Random token for an UNAUTHENTICATED public view/download of an ISSUED document
    # (letter/report — no cost/margin data; the body is a sanitised snapshot). Minted once
    # on issue (see services.generated_documents.issue_document), by the same pattern as
    # Quote.public_access_token. DRAFT/CANCELLED never carry a live link.
    public_access_token = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Публичный токен доступа"),
        help_text=_("Секретный токен для просмотра/скачивания выпущенного документа без входа"),
    )
    public_token_revoked = models.BooleanField(
        default=False,
        verbose_name=_("Публичная ссылка отозвана"),
        help_text=_("Если включено — публичная ссылка на документ больше не открывается (410)"),
    )
    public_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Публичная ссылка истекает"),
        help_text=_("Явный TTL публичной ссылки. NULL — без отдельного TTL."),
    )
    issued_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата выпуска"))
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_generated_documents",
        verbose_name=_("Кем создан"),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Дата создания"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Дата обновления"))

    class Meta:
        verbose_name = _("Сгенерированный документ")
        verbose_name_plural = _("Сгенерированные документы")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "status"], name="gendoc_company_status_idx"),
            models.Index(fields=["deal"], name="gendoc_deal_idx"),
        ]

    def __str__(self):
        return f"{self.number} — {self.title or self.template_id}"

    @property
    def status_code(self):
        return self.status.code if self.status_id else None
