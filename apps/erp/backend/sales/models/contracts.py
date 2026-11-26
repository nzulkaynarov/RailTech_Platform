import pghistory
import pgtrigger
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.contract_term import ContractRenewalMode, ContractTermRule, DeclinedBy
from core.models import Currency
from core.storage import contract_pdf_path, contract_remark_path, contract_signed_path, get_private_storage

from .lookups import ContractStatus


@pghistory.track(
    pghistory.RowEvent("contract.snapshot", row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent("contract.before_update", row=pghistory.Old, operation=pgtrigger.Update),
)
class Contract(models.Model):
    """Контракт, формируемый из одобренного Quote. Двусторонняя подпись."""

    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name=_("Сделка"),
    )
    quote = models.ForeignKey(
        "sales.Quote",
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
        ContractStatus,
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
    frozen_template_body = models.TextField(blank=True, default="")
    # ДОК-10: договор собран из утверждённого шаблона; редакция фиксируется и после выхода новой не меняется.
    template = models.ForeignKey(
        "documents.DocumentTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts",
        verbose_name=_("Шаблон"),
    )
    template_edition = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_("Редакция шаблона"))
    # Отступление от шаблона: заявка держателю «Право»; до решения договор клиенту не уходит.
    deviation_text = models.TextField(blank=True, default="", verbose_name=_("Отступление от шаблона"))
    deviation_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто запросил отступление"),
    )
    deviation_requested_at = models.DateTimeField(null=True, blank=True)
    deviation_decision = models.CharField(
        max_length=16,
        blank=True,
        default="",
        choices=[("approved", _("Одобрено")), ("rejected", _("Отклонено"))],
        verbose_name=_("Решение по отступлению"),
    )
    deviation_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто решил по отступлению"),
    )
    deviation_decided_at = models.DateTimeField(null=True, blank=True)
    wording_selections = models.JSONField(default=dict, blank=True, verbose_name=_("Формулировки договора"))
    signed_file = models.FileField(
        upload_to=contract_signed_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Подписанный скан/скан-копия"),
    )

    client_signer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts_signed_as_client",
        verbose_name=_("Подписал со стороны клиента"),
    )
    client_signed_at = models.DateTimeField(null=True, blank=True)
    manager_signer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts_signed_as_manager",
        verbose_name=_("Подписал со стороны продавца"),
    )
    manager_signed_at = models.DateTimeField(null=True, blank=True)

    # Регламентированная официальная подпись (SIGN-4, ADR-0024)
    verification_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Код проверки подлинности"),
        help_text=_("10-значный криптографический код проверки (ADR-0024, SIGN-4)"),
    )
    signatory_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("ФИО подписанта"),
    )
    signatory_position = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Должность подписанта"),
    )
    signatory_basis = models.CharField(
        max_length=32,
        blank=True,
        default="",
        choices=[("charter", _("Устав")), ("order", _("Приказ")), ("power_of_attorney", _("Доверенность"))],
        verbose_name=_("Основание полномочия"),
    )
    signatory_basis_text = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Формулировка основания"),
    )
    signed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Дата и время подписания"),
    )

    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    # ДС-1: срок считается из правила при подписании (`crm/services/contract_term.py`) и хранится вместе с редакцией шаблона.
    term_rule = models.CharField(
        max_length=16, choices=ContractTermRule.choices, blank=True, default="", verbose_name=_("Правило срока")
    )
    renewal_mode = models.CharField(
        max_length=16, choices=ContractRenewalMode.choices, blank=True, default="", verbose_name=_("Продление")
    )
    notice_days = models.PositiveSmallIntegerField(default=0, verbose_name=_("Дней на отказ от продления"))
    last_notice_date = models.DateField(
        null=True, blank=True, db_index=True, verbose_name=_("Последний день отказа от продления")
    )
    term_foreign = models.BooleanField(default=False, verbose_name=_("Иностранный контрагент"))
    renewals_count = models.PositiveSmallIntegerField(default=0, verbose_name=_("Продлений"))
    renewal_declined_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Отказ от продления"))
    renewal_declined_by = models.CharField(
        max_length=8, choices=DeclinedBy.choices, blank=True, default="", verbose_name=_("Кто отказался от продления")
    )
    term_reminders = models.JSONField(
        default=list, blank=True, verbose_name=_("Отправленные напоминания"), help_text=_("Метки вида `30:2026-12-01`")
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
        verbose_name=_("Заменяет договор"),
        help_text=_("Новая редакция шаблона на подпись: прежний договор действует до её подписания."),
    )
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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
        return self.status.code if self.status_id else None

    @property
    def is_fully_signed(self) -> bool:
        return self.status_code == "SIGNED" and bool(self.client_signed_at and self.manager_signed_at)


class ContractRemark(models.Model):
    """ДП-1: замечания контрагента к редакции договора («Есть замечания», один ответ: комментарий + своя редакция DOCX/XLSX).

    Факты, из которых карточка и Кабинет выводят «что дальше»: `resolution` пуст — замечания на согласовании у наших
    ответственных (`ContractRemarkVote`), `accepted` — редакция контрагента принята (договор «Согласован»), `countered` —
    мы ответили своей редакцией (`response`), договор остаётся у контрагента. Файл — вложение и точка правды; разбор
    (`summary`, `items`) считается при получении и хранится вместе с замечанием.
    """

    ACCEPTED = "accepted"
    COUNTERED = "countered"

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="remarks")
    edition = models.PositiveSmallIntegerField(default=1, verbose_name=_("Редакция, к которой замечания"))
    comment = models.TextField(verbose_name=_("Комментарий контрагента"))
    file = models.FileField(
        upload_to=contract_remark_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Редакция контрагента"),
    )
    file_name = models.CharField(max_length=255, blank=True, default="")
    author_name = models.CharField(max_length=200, blank=True, default="")
    summary = models.JSONField(default=dict, blank=True, verbose_name=_("Краткий разбор"))
    items = models.JSONField(default=list, blank=True, verbose_name=_("Что изменилось по пунктам"))
    resolution = models.CharField(max_length=16, blank=True, default="", db_index=True)
    response = models.TextField(blank=True, default="", verbose_name=_("Наш ответ контрагенту"))
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Замечания к договору")
        verbose_name_plural = _("Замечания к договору")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract"], condition=models.Q(resolution=""), name="contract_one_open_remark"
            )
        ]


class ContractRemarkVote(models.Model):
    """Ответ одного из ответственных за договор на замечания: «Согласен» или «Не согласен» (с комментарием)."""

    remark = models.ForeignKey(ContractRemark, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    agree = models.BooleanField()
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["remark", "user"], name="contract_remark_one_vote_per_user")]
