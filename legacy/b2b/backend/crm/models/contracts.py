import pghistory
import pgtrigger
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import contract_pdf_path, contract_signed_path, get_private_storage
from master_data.models import Currency

# ────────────────────────────────────────────
# Справочники модуля CRM
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# Контракты, счета, оплаты, акты — post-sale
# ────────────────────────────────────────────


@pghistory.track(
    pghistory.RowEvent("contract.snapshot", row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent("contract.before_update", row=pghistory.Old, operation=pgtrigger.Update),
)
class Contract(models.Model):
    """Контракт, формируемый из одобренного Quote. Двусторонняя подпись."""

    deal = models.ForeignKey(
        "crm.Deal",
        on_delete=models.PROTECT,  # financial record must survive deal deletion
        related_name="contracts",
        verbose_name=_("Сделка"),
    )
    quote = models.ForeignKey(
        "crm.Quote",
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name=_("КП-источник"),
    )
    number = models.CharField(
        max_length=64,
        unique=True,
        verbose_name=_("Номер контракта"),
    )
    status = models.ForeignKey(
        "crm.ContractStatus",
        on_delete=models.PROTECT,
        related_name="contracts",
        null=True,
        db_index=True,
        verbose_name=_("Статус"),
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("Сумма контракта"),
    )
    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта"),
    )

    pdf_file = models.FileField(
        upload_to=contract_pdf_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("PDF контракта"),
    )
    # E3: редакция шаблона на момент СОЗДАНИЯ договора (он сразу уходит клиенту на подпись).
    # Перерендер при подписании обновляет блоки (ПЭП-штампы — живые данные), но печатает
    # замороженный ТЕКСТ статей. Пусто = создан до E3, рендерится по живому шаблону.
    frozen_template_body = models.TextField(blank=True, default="")
    # E4: формулировки ЭТОГО договора {field: text}. Заполняются при создании резолвом D1
    # (профиль -> платформа) и правятся ВЫБОРОМ согласованного варианта до подписания -
    # менеджер отвечает юристу контрагента, не трогая шаблон всей компании. Одновременно это
    # снапшот: перерендер после подписи печатает зафиксированный текст, а не сегодняшний
    # профиль (закрывает дыру E3 - формулировки резолвились живьём).
    wording_selections = models.JSONField(default=dict, blank=True, verbose_name=_("Формулировки договора"))
    signed_file = models.FileField(
        upload_to=contract_signed_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Подписанный скан/скан-копия"),
    )

    client_signer = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts_signed_as_client",
        verbose_name=_("Подписал со стороны клиента"),
    )
    client_signed_at = models.DateTimeField(null=True, blank=True)
    manager_signer = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts_signed_as_manager",
        verbose_name=_("Подписал со стороны продавца"),
    )
    manager_signed_at = models.DateTimeField(null=True, blank=True)

    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts_created",
        verbose_name=_("Создал"),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Контракт")
        verbose_name_plural = _("Контракты")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Contract {self.number} ({self.status_code})"

    @property
    def status_code(self):
        """Null-safe status code — status is a FK lookup now (F5.4)."""
        return self.status.code if self.status_id else None

    @property
    def is_fully_signed(self) -> bool:
        return self.status_code == "SIGNED" and bool(self.client_signed_at and self.manager_signed_at)
