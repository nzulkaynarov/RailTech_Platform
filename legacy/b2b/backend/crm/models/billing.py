from decimal import Decimal

import pghistory
import pgtrigger
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import act_pdf_path, get_private_storage, invoice_pdf_path, payment_proof_path
from master_data.models import Currency

# ────────────────────────────────────────────
# Справочники модуля CRM
# ────────────────────────────────────────────


# Financial records are the most audit-critical entities — track an immutable
# row-history (snapshot on insert/update + the pre-update row) like Deal/Quote do.
@pghistory.track(
    pghistory.RowEvent("invoice.snapshot", row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent("invoice.before_update", row=pghistory.Old, operation=pgtrigger.Update),
)
class Invoice(models.Model):
    """Инвойс на оплату по контракту."""

    deal = models.ForeignKey(
        "crm.Deal",
        # PROTECT, not CASCADE: a financial record must never be silently deleted
        # by removing its deal. Deals are deletable only while DRAFT (no invoices),
        # so this never blocks a legitimate deletion — it's a safety net.
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name=_("Сделка"),
    )
    contract = models.ForeignKey(
        "crm.Contract",
        on_delete=models.PROTECT,
        related_name="invoices",
        null=True,
        blank=True,
        verbose_name=_("Контракт"),
    )
    number = models.CharField(max_length=64, unique=True, verbose_name=_("Номер инвойса"))
    status = models.ForeignKey(
        "crm.InvoiceStatus",
        on_delete=models.PROTECT,
        related_name="invoices",
        null=True,
        db_index=True,
        verbose_name=_("Статус"),
    )
    issued_at = models.DateField(null=True, blank=True, verbose_name=_("Дата выставления"))
    due_date = models.DateField(null=True, blank=True, verbose_name=_("Срок оплаты"))
    # Срок оплаты по умолчанию пересчитывается от даты ВЫСТАВЛЕНИЯ счёта, иначе пролежавший
    # неделю черновик отдавал бы покупателю уже наполовину истёкший срок. Но если продавец
    # задал дату руками (особые условия договора), пересчёт её затёр бы — отсюда признак.
    due_date_is_manual = models.BooleanField(
        default=False,
        verbose_name=_("Срок оплаты задан вручную"),
        help_text=_("Установлен продавцом явно — не пересчитывается при выставлении счёта"),
    )
    # Состояние процесса напоминаний, а НЕ статус просрочки. Просрочка остаётся вычисляемой
    # (эталоны её не хранят — у Stripe `past_due` вообще не статус счёта, у Odoo и QuickBooks
    # она выводится из срока и остатка). Хранить нужно ровно одно: было ли уже отправлено
    # напоминание, иначе ежедневная задача слала бы его каждый день.
    payment_reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Напоминание об оплате отправлено"),
    )

    subtotal_excl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_incl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    pdf_file = models.FileField(
        upload_to=invoice_pdf_path,
        storage=get_private_storage,
        null=True,
        blank=True,
    )
    # E3 (spec-editable-outgoing-documents): редакция шаблона, действовавшая на момент
    # ВЫСТАВЛЕНИЯ. Перерендер (смена бренда, invalidate_document_pdfs) печатает этот текст,
    # а не сегодняшний шаблон — правка шаблона задним числом не меняет выпущенный счёт.
    # Пусто = документ выпущен до E3 либо ещё черновик (черновик следует за живым шаблоном).
    frozen_template_body = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices_created",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Инвойс")
        verbose_name_plural = _("Инвойсы")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invoice {self.number}"

    @property
    def status_code(self):
        """Null-safe status code — status is a FK lookup now (F5.4)."""
        return self.status.code if self.status_id else None

    @property
    def balance_due(self) -> Decimal:
        return Decimal(self.total_incl_vat) - Decimal(self.amount_paid or 0)


class InvoiceItem(models.Model):
    """Позиция инвойса (копия QuoteItem на момент выставления)."""

    invoice = models.ForeignKey(
        "crm.Invoice",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Инвойс"),
    )
    description = models.CharField(max_length=500)
    quantity = models.PositiveIntegerField(default=1)
    unit_price_excl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    line_total_excl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    source_quote_item = models.ForeignKey(
        "crm.QuoteItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = _("Позиция инвойса")
        verbose_name_plural = _("Позиции инвойсов")

    def __str__(self):
        return f"{self.description} x{self.quantity}"


@pghistory.track(
    pghistory.RowEvent("payment.snapshot", row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent("payment.before_update", row=pghistory.Old, operation=pgtrigger.Update),
)
class Payment(models.Model):
    """Платёж по инвойсу."""

    METHOD_CHOICES = [
        ("BANK_TRANSFER", _("Банковский перевод")),
        ("CARD", _("Банковская карта")),
        ("CASH", _("Наличные")),
        ("OTHER", _("Другое")),
    ]

    invoice = models.ForeignKey(
        "crm.Invoice",
        # PROTECT: a recorded payment must outlive deletion of its invoice
        # (invoices are not deleted in normal flow; this prevents silent loss).
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name=_("Инвойс"),
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default="BANK_TRANSFER")
    paid_at = models.DateField(verbose_name=_("Дата платежа"))
    reference = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Референс / номер операции"),
    )
    proof_file = models.FileField(
        upload_to=payment_proof_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Подтверждение"),
    )
    recorded_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Платёж")
        verbose_name_plural = _("Платежи")
        ordering = ["-paid_at"]
        constraints = [
            # A bank reference uniquely identifies a real-world payment. Enforce
            # at the DB level so a double-submit with the same reference cannot
            # double-count amount_paid, even on a code path that skips the
            # service-layer check. Blank references are allowed to repeat.
            models.UniqueConstraint(
                fields=["invoice", "reference"],
                condition=~models.Q(reference=""),
                name="uniq_payment_invoice_reference",
            ),
        ]

    def __str__(self):
        return f"Payment {self.amount} on {self.paid_at}"


@pghistory.track(
    pghistory.RowEvent("act.snapshot", row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent("act.before_update", row=pghistory.Old, operation=pgtrigger.Update),
)
class Act(models.Model):
    """Акт выполненных работ / приёма-передачи."""

    deal = models.ForeignKey(
        "crm.Deal",
        on_delete=models.PROTECT,  # financial record must survive deal deletion
        related_name="acts",
        verbose_name=_("Сделка"),
    )
    contract = models.ForeignKey(
        "crm.Contract",
        on_delete=models.PROTECT,
        related_name="acts",
        null=True,
        blank=True,
    )
    invoice = models.ForeignKey(
        "crm.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acts",
    )
    number = models.CharField(max_length=64, unique=True, verbose_name=_("Номер акта"))
    status = models.ForeignKey(
        "crm.ActStatus",
        on_delete=models.PROTECT,
        related_name="acts",
        null=True,
        db_index=True,
        verbose_name=_("Статус"),
    )
    issued_at = models.DateField(null=True, blank=True)
    # Момент, когда акт стал закрытым (согласован обеими сторонами). Оставлен как есть —
    # на него смотрят реестры, PDF и аналитика; заполняется по приёму второй стороной.
    signed_at = models.DateTimeField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # ── Две стороны акта (G2) ────────────────────────────────────────────────
    # Акт — двусторонний документ: в узбекской практике он «подтверждён двумя сторонами»
    # (и ГК РУз ст. 646 привязывает возражения заказчика по недостаткам именно к акту
    # приёмки), в российском ЭДО он физически состоит из двух титулов — исполнителя и
    # заказчика. Односторонняя подпись — форма СЧЁТА, а не акта.
    #
    # Раньше здесь было одно поле `signed_at` и НИ ОДНОГО подписанта: кто закрыл документ,
    # нигде не сохранялось, и закрыть его в одиночку могла любая сторона. Модель приведена
    # к той, что уже есть у договора рядом (client_signer / manager_signer).
    issuer_signer = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acts_issued",
        verbose_name=_("Выпустил (сторона исполнителя)"),
    )
    issuer_signed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Выпущен"))
    acceptor_signer = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acts_accepted",
        verbose_name=_("Принял (сторона заказчика)"),
    )
    acceptor_signed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Принят"))
    rejection_reason = models.TextField(
        blank=True,
        verbose_name=_("Причина отклонения"),
        help_text=_("Заполняется, когда заказчик отклоняет акт: основание попадает в аудит"),
    )
    cancellation_reason = models.TextField(
        blank=True,
        verbose_name=_("Причина аннулирования"),
        help_text=_(
            "Заполняется, когда акт аннулирует ВЫПУСТИВШАЯ сторона. Отдельно от причины "
            "отклонения: отклонение — ответ заказчика, аннулирование — отзыв исполнителя, и "
            "смешивать их в одном поле значит терять, кто именно закрыл документ."
        ),
    )
    # Состояние ПРОЦЕССА напоминаний, а не статус документа — тот же приём, что у
    # `Invoice.payment_reminder_sent_at`. Хранится ради ограничения частоты: ручное
    # напоминание разрешено не чаще раза в сутки (PandaDoc), иначе кнопка превращается
    # в инструмент спама, а домен отправителя платит за это доставляемостью.
    reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Напоминание отправлено"),
    )

    pdf_file = models.FileField(
        upload_to=act_pdf_path,
        storage=get_private_storage,
        null=True,
        blank=True,
    )
    # E3: редакция шаблона на момент ВЫПУСКА акта. Перерендер после подписания обновляет
    # блоки (штампы подписей — живые данные), но печатает замороженный ТЕКСТ — правка
    # шаблона между выпуском и подписью не переписывает документ. Пусто = выпущен до E3.
    frozen_template_body = models.TextField(blank=True, default="")
    # E4: снапшот формулировок акта {field: text} на момент выпуска - оговорка не меняется
    # перерендером после правки профиля (та же дыра E3, что у договора).
    wording_selections = models.JSONField(default=dict, blank=True, verbose_name=_("Формулировки акта"))
    signed_file = models.FileField(
        upload_to=act_pdf_path,
        storage=get_private_storage,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Акт")
        verbose_name_plural = _("Акты")
        ordering = ["-created_at"]

    @property
    def status_code(self):
        """Null-safe status code — status is a FK lookup now (F5.4)."""
        return self.status.code if self.status_id else None

    @property
    def is_fully_signed(self) -> bool:
        """Согласован обеими сторонами — зеркало `Contract.is_fully_signed`."""
        return self.status_code == "SIGNED" and bool(self.issuer_signed_at and self.acceptor_signed_at)

    def __str__(self):
        return f"Act {self.number} ({self.status_code})"
