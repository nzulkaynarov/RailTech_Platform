"""CompanyDocumentProfile — брендированные реквизиты и формулировки документов (D1/D2)."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import company_document_profile_logo_path, get_public_storage


class CompanyDocumentProfile(models.Model):
    """Branded requisites a company prints on its OWN commercial documents (КП, договор).

    Tenant org-admin (OWNER) fills it once: legal name, ИНН, юр.адрес, банковские
    реквизиты, подписант, логотип, колонтитул. The КП / contract documents render the
    «Поставщик» block from this profile instead of the hardcoded platform name, so each
    selling company issues offers under its OWN brand. One profile per company.
    """

    company = models.OneToOneField(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="document_profile_rel",
        verbose_name=_("Компания"),
        help_text=_("Организация, чьи документы оформляются по этому профилю"),
    )
    logo = models.ImageField(
        upload_to=company_document_profile_logo_path,
        storage=get_public_storage,
        null=True,
        blank=True,
        verbose_name=_("Логотип для документов"),
        help_text=_("Логотип, печатаемый в шапке КП / договора"),
    )
    legal_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Полное юридическое наименование"),
        help_text=_("Наименование организации для документов (напр. ООО «РемПуть»)"),
    )
    inn = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("ИНН"),
        help_text=_("ИНН организации для реквизитов в документах"),
    )
    legal_address = models.TextField(
        blank=True,
        verbose_name=_("Юридический адрес"),
        help_text=_("Юридический адрес для реквизитов в документах"),
    )
    bank_details = models.TextField(
        blank=True,
        verbose_name=_("Банковские реквизиты"),
        help_text=_("Р/с, банк, МФО, корр. счёт и пр."),
    )
    signatory_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("ФИО подписанта"),
        help_text=_("Лицо, подписывающее документы от имени компании"),
    )
    signatory_position = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Должность подписанта"),
        help_text=_("Должность подписанта (напр. Генеральный директор)"),
    )
    footer_text = models.TextField(
        blank=True,
        verbose_name=_("Колонтитул / оговорка"),
        help_text=_("Текст внизу документа: дисклеймер, условия, контакты"),
    )
    accent_color = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Акцентный цвет"),
        help_text=_("HEX-цвет фирменного стиля для шапки документа (напр. #15294d)"),
    )
    # ── Document theme (Odoo Document Layout / PandaDoc Themes model) ──────────
    # One theme drives ALL the company's PDFs (КП / договор / инвойс / акт / письмо):
    # a named layout preset + font pair + secondary tint, applied by _document_base.html.
    LAYOUT_LIGHT = "light"
    LAYOUT_BOXED = "boxed"
    LAYOUT_BOLD = "bold"
    LAYOUT_STRIPED = "striped"
    LAYOUT_CHOICES = [
        (LAYOUT_LIGHT, _("Светлый")),
        (LAYOUT_BOXED, _("В рамках")),
        (LAYOUT_BOLD, _("Контрастный")),
        (LAYOUT_STRIPED, _("Полосатый")),
    ]
    FONT_SANS = "sans"
    FONT_SERIF = "serif"
    FONT_CHOICES = [
        (FONT_SANS, _("Гротеск (без засечек)")),
        (FONT_SERIF, _("Антиква (с засечками)")),
    ]
    layout_preset = models.CharField(
        max_length=16,
        choices=LAYOUT_CHOICES,
        default=LAYOUT_LIGHT,
        verbose_name=_("Макет документов"),
        help_text=_("Именованный макет оформления всех PDF компании (как в Odoo Document Layout)"),
    )
    font_family = models.CharField(
        max_length=16,
        choices=FONT_CHOICES,
        default=FONT_SANS,
        verbose_name=_("Шрифт документов"),
        help_text=_("Гарнитура всех PDF компании (кириллица поддерживается обеими)"),
    )
    secondary_color = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Второй цвет"),
        help_text=_("HEX-цвет подложек и полос таблиц (напр. #f6f8fb); пусто — нейтральный"),
    )
    use_company_defaults = models.BooleanField(
        default=True,
        verbose_name=_("Использовать реквизиты компании"),
        help_text=_("Автоматически наследовать название, ИНН и адрес из профиля компании"),
    )
    # ── Layout toggles (P3 document-settings) — what the seller shows on its documents ──
    show_logo = models.BooleanField(
        default=True,
        verbose_name=_("Показывать логотип"),
        help_text=_("Печатать логотип в шапке документов"),
    )
    show_lead_time = models.BooleanField(
        default=True,
        verbose_name=_("Показывать колонку «Срок»"),
        help_text=_("Колонка срока поставки по позициям в КП"),
    )
    show_fx_note = models.BooleanField(
        default=False,
        verbose_name=_("Показывать курс ЦБ в КП"),
        help_text=_("Печатать курс ЦБ (FX-базис) на клиентском КП. По умолчанию скрыто — клиент видит цену в сумах."),
    )
    # ── КП «фирменный бланк» (spec-kp-blank) ──────────────────────────────────
    # Сопроводительный абзац = «КП + письмо в одном» (СНГ-практика). Хранится как ПЛОСКИЙ
    # текст; при рендере несколько токенов ({{buyer}}/{{deal}}/{{seller}}) подставляются
    # значениями и Django авто-эскейпит — НЕ рендерится как шаблон (без SSTI).
    cover_letter_text = models.TextField(
        blank=True,
        verbose_name=_("Сопроводительный текст КП"),
        help_text=_("Вступительный абзац перед таблицей. Токены: {{buyer}}, {{deal}}, {{seller}}."),
    )
    show_cover_letter = models.BooleanField(
        default=False,
        verbose_name=_("Печатать сопроводительный текст"),
        help_text=_("Добавлять вступительный абзац в начало КП"),
    )
    # ── Формулировки документов (spec-documents-editable-and-uniform) ────────
    # Каркас документа остаётся кодом, а ПРОЗА становится данными — так границу проводят
    # эталоны отчётов (Odoo: настраиваемый текст в полях модели, структура в шаблоне).
    # Пустое поле = печатать платформенную формулировку из `crm.document_wording`, а не пусто:
    # компания, которая ничего не настраивала, получает ровно прежний документ.
    contract_acceptance_text = models.TextField(
        blank=True,
        verbose_name=_("Договор: качество и приёмка"),
        help_text=_("Пункт «Качество, комплектность и приёмка». Пусто — печатается стандартная формулировка."),
    )
    contract_liability_text = models.TextField(
        blank=True,
        verbose_name=_("Договор: ответственность сторон"),
        help_text=_("Пункт «Ответственность сторон» — здесь компании чаще всего меняют ставку неустойки."),
    )
    contract_extra_terms_text = models.TextField(
        blank=True,
        verbose_name=_("Договор: особые условия"),
        help_text=_("Дополнительный пункт договора. Печатается, ТОЛЬКО если заполнен."),
    )
    act_closing_text = models.TextField(
        blank=True,
        verbose_name=_("Акт: оговорка о приёмке"),
        help_text=_("Абзац под таблицей акта об объёме и отсутствии претензий."),
    )
    show_bank_in_header = models.BooleanField(
        default=True,
        verbose_name=_("Банковские реквизиты в шапке"),
        help_text=_("Печатать банк/МФО/р-с в шапке документа (СНГ-практика). Выкл — только в блоке «Поставщик»."),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлён"))

    class Meta:
        verbose_name = _("Профиль документов компании")
        verbose_name_plural = _("Профили документов компаний")

    def __str__(self):
        return f"Документы: {self.company.name}"
