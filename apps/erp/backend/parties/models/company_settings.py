"""CompanySettings — машинные настройки компании (payment_terms_days и т.п.)."""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from catalog.constants import (
    DEFAULT_OFFER_CONFIRM_DAYS,
    DEFAULT_OFFER_EXPIRING_DAYS,
    DEFAULT_PUBLISH_THRESHOLD,
    PriceVisibility,
)
from core.contract_term import ContractExpiredAction, ContractTermRule


class CompanySettings(models.Model):
    """Per-company КП defaults + the document-numbering scheme.

    The selling company sets these once (OWNER-gated). New КП built by the company
    pre-fill from `default_*` so the seller team isn't re-entering the same Incoterm,
    valuta, ставку НДС, маржу and validity on every offer. `doc_number_prefix` brands
    the company's own document numbering (contracts/invoices/acts): with prefix "ACME"
    a contract reads `ACME-ДОГ-2026/001`; without it the platform default `ДОГ-2026/001`.
    One settings row per company (get-or-create via the `Company.settings` accessor).
    """

    company = models.OneToOneField(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="settings_rel",
        verbose_name=_("Компания"),
        help_text=_("Организация, к которой относятся настройки"),
    )

    # ── КП defaults (inherited by a new Quote on CREATE only) ──────────────────
    default_delivery_basis = models.ForeignKey(
        "core.DeliveryBasis",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Базис поставки по умолчанию"),
        help_text=_("Incoterm, подставляемый в новый КП (FCA, CIP, DDP …)"),
    )
    default_cost_currency = models.ForeignKey(
        "core.Currency",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта себестоимости по умолчанию"),
        help_text=_("Валюта базовой цены, наследуемая новыми позициями КП"),
    )
    default_vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Ставка НДС по умолчанию (%)"),
        help_text=_("Ставка НДС, подставляемая в новый КП"),
    )
    default_margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Маржа по умолчанию (%)"),
        help_text=_("Наценка на себестоимость, подставляемая в новый КП"),
    )
    default_offer_validity_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Срок действия КП по умолчанию (дней)"),
        help_text=_("Через сколько дней истекает новый КП (valid_until = сегодня + N)"),
    )
    payment_terms_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Срок оплаты счёта (дней)"),
        help_text=_(
            "Через сколько дней после ВЫСТАВЛЕНИЯ счёт должен быть оплачен. "
            "Пусто — платформенное умолчание. От этого срока считается напоминание об оплате."
        ),
    )
    remind_overdue_invoices = models.BooleanField(
        default=False,
        verbose_name=_("Напоминать клиентам о просроченных счетах"),
        help_text=_(
            "Раз в сутки (10:00 по Ташкенту) — одно напоминание по каждому просроченному счёту контактам клиента: колокольчик "
            "кабинета и письмо. По умолчанию выключено (DECISIONS 2026-11-04, эталон Stripe и QuickBooks)."
        ),
    )
    default_payment_terms = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Условия оплаты по умолчанию"),
        help_text=_("Напр. «100% предоплата» — подставляется в блок «Условия поставки» КП"),
    )
    default_warranty_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Гарантия по умолчанию (мес.)"),
        help_text=_("Срок гарантии в месяцах для блока «Условия поставки» КП"),
    )
    min_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=15,
        verbose_name=_("Порог маржи (%)"),
        help_text=_("Минимальная валовая маржа (на цене). Ниже — КП требует согласования."),
    )
    target_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=25,
        verbose_name=_("Целевая маржа (%)"),
        help_text=_("Желаемая валовая маржа (на цене) — зелёная зона в конструкторе КП."),
    )

    # ── Договор из шаблона (ДОК-10, DECISIONS 2026-11-23): правила — данные, не код ──────────
    contract_auto_send = models.BooleanField(
        default=True,
        verbose_name=_("Договор по шаблону сам уходит в Кабинет"),
        help_text=_("После принятия КП договор по утверждённому шаблону без отступлений уходит клиенту без визы."),
    )
    contract_sign_before_send = models.BooleanField(
        default=True,
        verbose_name=_("Наша подпись до отправки"),
        help_text=_("Договор уходит клиенту после подписи от компании; выключено — сразу."),
    )
    contract_deviations_allowed = models.BooleanField(
        default=True,
        verbose_name=_("Отступления от шаблона по заявке"),
        help_text=_("Выключено — «Запросить отступление» недоступно."),
    )
    # РЕЗ-1 (owner 2026-11-25): резолюция директора перед расчётом — настройка, а не зашитый шаг.
    request_resolution = models.CharField(
        max_length=16,
        choices=[("always", "always"), ("never", "never")],
        default="always",
        verbose_name=_("Резолюция перед расчётом"),
        help_text=_("always — у каждой заявки; never — не нужна, заявка сразу в расчёт ответственному."),
    )
    contract_four_eyes = models.BooleanField(
        default=True,
        verbose_name=_("Решение по своему договору — другим держателем «Права»"),
        help_text=_(
            "Включено — подготовивший договор партнёра не решает по нему сам; единственный держатель права решает "
            "самостоятельно с подтверждением и записью в журнале."
        ),
    )
    default_client_contract_template = models.ForeignKey(
        "documents.DocumentTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Шаблон договора по умолчанию: клиент"),
    )
    default_partner_contract_template = models.ForeignKey(
        "documents.DocumentTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Шаблон договора по умолчанию: партнёр"),
    )

    # ── Срок договора (ДС-1, решение владельца 2026-11-25): правило — данные, не код ───────────────────────────────
    contract_term_rule = models.CharField(
        max_length=16,
        choices=ContractTermRule.choices,
        default=ContractTermRule.CALENDAR_YEAR,
        verbose_name=_("Срок договора по умолчанию"),
        help_text=_("До 31 декабря года подписания, 12 месяцев с подписания или без срока. Шаблон может задать своё."),
    )
    contract_auto_renew = models.BooleanField(
        default=True,
        verbose_name=_("Договор продлевается сам"),
        help_text=_("На следующий срок, если ни одна сторона не отказалась до последнего дня уведомления."),
    )
    contract_notice_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(0), MaxValueValidator(365)],
        verbose_name=_("За сколько дней отказаться от продления"),
    )
    contract_next_year_from_day = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        verbose_name=_("С какого числа декабря первый срок — до конца следующего года"),
    )
    contract_remind_first_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
        verbose_name=_("Первое напоминание: за сколько дней до последнего дня уведомления"),
    )
    contract_remind_last_days = models.PositiveSmallIntegerField(
        default=7,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
        verbose_name=_("Второе напоминание: за сколько дней до последнего дня уведомления"),
    )
    contract_foreign_remind_days = models.PositiveSmallIntegerField(
        default=45,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
        verbose_name=_("Иностранный контрагент: напомнить о доп. соглашении за дней до конца срока"),
    )
    contract_foreign_by_agreement = models.BooleanField(
        default=True,
        verbose_name=_("Нерезидент продлевается соглашением"),
        help_text=_(
            "Страна контрагента отличается от страны компании: вместо автопродления — напоминание и соглашение."
        ),
    )
    contract_gating_kinds = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Какие договоры ограничивают новые сделки"),
        help_text=_(
            "Подмножество `partner`, `supply`, `services`. По умолчанию пусто: срок договора по сделке новое КП не закрывает."
        ),
    )
    contract_expired_action = models.CharField(
        max_length=8,
        choices=ContractExpiredAction.choices,
        default=ContractExpiredAction.BLOCK,
        verbose_name=_("Что делать после окончания срока"),
        help_text=_("Касается только новых КП и сделок; начатая работа, оплаты и претензии не блокируются никогда."),
    )

    # ── Политики каталога (M1-ERP-07, ARCHITECTURE §7) ────────────────────────
    catalog_price_visibility = models.CharField(
        max_length=16,
        choices=PriceVisibility.choices,
        default=PriceVisibility.ON_REQUEST,
        verbose_name=_("Видимость цен каталога по умолчанию"),
        help_text=_("Для карточек без своей политики: цена в кабинете клиента или «по запросу»."),
    )
    catalog_publish_threshold = models.PositiveSmallIntegerField(
        default=DEFAULT_PUBLISH_THRESHOLD,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        verbose_name=_("Порог публикации (%)"),
        help_text=_("Минимальная полнота карточки, при которой её можно опубликовать."),
    )
    #: X-16: что обязательно для публикации карточки — МХИК у позиции, которую продаём, ТН ВЭД у ввозимой. Проверяет
    #: `catalog.completeness` при публикации; уже опубликованные карточки остаются, проверка — при следующей публикации.
    catalog_require_mxik = models.BooleanField(
        default=True,
        verbose_name=_("МХИК обязателен для публикации"),
        help_text=_("Карточку без кода МХИК (ИКПУ) опубликовать нельзя: он нужен в счёте-фактуре."),
    )
    catalog_require_hs_imported = models.BooleanField(
        default=True,
        verbose_name=_("ТН ВЭД обязателен для ввозимого товара"),
        help_text=_("Товар не из Узбекистана (или страна не указана) без кода ТН ВЭД опубликовать нельзя."),
    )
    #: PART-2: через сколько дней без подтверждения цена поставщика считается устаревшей (признак «устарела» в кабинете партнёра).
    offer_confirm_days = models.PositiveSmallIntegerField(
        default=DEFAULT_OFFER_CONFIRM_DAYS,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
        verbose_name=_("Срок подтверждения цен поставщика (дней)"),
        help_text=_("Цена поставщика без подтверждения дольше этого срока помечается «устарела»."),
    )
    #: Задача «Н3c»: за сколько дней до окончания срока цена партнёра помечается «истекает» (каталог и кабинет партнёра).
    offer_expiring_days = models.PositiveSmallIntegerField(
        default=DEFAULT_OFFER_EXPIRING_DAYS,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
        verbose_name=_("Предупреждать об окончании цены (дней)"),
        help_text=_("Цена поставщика со сроком действия ближе этого числа дней помечается «истекает»."),
    )
    #: Задача «Н3c»: не чаще одного напоминания клиенту об акте за столько часов.
    act_reminder_hours = models.PositiveSmallIntegerField(
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(720)],
        verbose_name=_("Пауза между напоминаниями об акте (часов)"),
    )

    # ── Политика курса и уведомления (M1-ERP-09, ARCHITECTURE §7) ────────────
    fx_rate_max_age_days = models.PositiveSmallIntegerField(
        default=7,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
        verbose_name=_("Максимальный возраст курса валюты (дней)"),
        help_text=_("Если курс ЦБ старше N дней, КП требует обновления курса или договорного курса."),
    )

    # ── Document numbering scheme ──────────────────────────────────────────────
    doc_number_prefix = models.CharField(
        max_length=16,
        blank=True,
        verbose_name=_("Префикс нумерации документов"),
        help_text=_("Префикс номеров документов компании (напр. «ACME» → ACME-CT-2026-00001)"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлён"))

    class Meta:
        verbose_name = _("Настройки компании")
        verbose_name_plural = _("Настройки компаний")

    def __str__(self):
        return f"Настройки: {self.company.name}"
