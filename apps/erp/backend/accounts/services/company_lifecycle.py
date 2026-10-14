"""
Жизненный цикл компании: удаление с историей запрещено, из оборота выводит АРХИВ.

Эталоны здесь единодушны, и это редкий случай, когда расхождений нет вовсе:

* **Odoo** — `active=False` (Archive) как штатная замена удалению, а удаление партнёра с
  бухгалтерской историей заблокировано доменной проверкой с сообщением, которое называет и
  причину, и средство: «The partner cannot be deleted because it is used in Accounting».
* **Salesforce** — пользователя удалить нельзя в принципе («users can never be deleted»),
  только деактивировать; способность удалить объявлена флагом заранее, чтобы кнопка не
  падала гарантированно.
* **Stripe** — финансовый факт не удаляется ничем: у `Charge` нет метода `delete`,
  финализированный счёт «must be voided»; у клиента остаётся «надгробие» со ссылками.
* **HubSpot** — удаление компании мягкое, обратимое 90 дней, и НЕ каскадит на её сделки.

У нас же `DELETE /accounts/companies/{id}/` был дефолтным `ModelViewSet.destroy`: замер
24-08 показал 204 и снос 2448 строк — вместе с компанией исчезали её сделки, а участники
оставались обезличенными аккаунтами без единого членства. Диалог при этом обещал ровно то,
что происходило («будет удалена со всеми связанными данными»), но не говорил о людях.

Поэтому запрет — не новая блокировка, а приведение к тому, что уже заявлено соседним
`can_delete_user` (`accounts/services/members.py`) и к тому, что делает каждый эталон.
"""

import logging
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from ..models import Company, CustomUser

logger = logging.getLogger(__name__)


def company_history_holders(company: Company) -> list[str]:
    """Кто держит компанию — списком КОДОВ, а не готовым текстом (Rule 5, подпись у витрины).

    Считается один раз при отказе, поэтому дешевизна выборок здесь не критична; важнее, что
    перечень полный: пропущенный держатель означает, что удаление снесёт его молча.
    """
    from crm.models import Contract, Deal, GeneratedDocument, Invoice, Quote

    holders: list[str] = []
    if Deal.objects.filter(company=company).exists():
        holders.append("deals")
    if Quote.objects.filter(seller_company=company).exists():
        holders.append("quotes")
    has_documents = (
        Contract.objects.filter(deal__company=company).exists()
        or Invoice.objects.filter(deal__company=company).exists()
        or GeneratedDocument.objects.filter(company=company).exists()
    )
    if has_documents:
        holders.append("documents")

    from catalog.models import SupplierOffer

    if SupplierOffer.objects.filter(supplier=company).exists():
        holders.append("offers")
    if company.members.filter(is_active=True).exists():
        holders.append("members")
    return holders


def can_delete_company(company: Company) -> Optional[str]:
    """Почему эту компанию нельзя удалить насовсем (или None, если можно).

    Возвращает код с машинным суффиксом — `COMPANY_HAS_HISTORY:deals,members`. Витрина
    локализует голову и перечисляет держателей: отказ обязан называть, ЧТО мешает, иначе
    оператор повторяет попытку (тот же формат, что у `LOOKUP_IN_USE` в справочниках).
    """
    holders = company_history_holders(company)
    if holders:
        return "COMPANY_HAS_HISTORY:" + ",".join(holders)
    return None


@transaction.atomic
def archive_company(
    company: Company,
    actor: CustomUser,
    reason: str = "",
) -> Tuple[Optional[Company], Optional[str]]:
    """Вывести компанию из оборота, сохранив её историю (паттерн Odoo Archive).

    Архивная компания исчезает из подбора продавцов, из книги контрагентов и из поиска, но
    её сделки, счета и подписанные документы остаются на месте и открываются как прежде:
    архив прячет из ОБОРОТА, а не из истории.

    Причина обязательна: это действие оператора над чужой компанией, и без основания
    запись в журнале бесполезна обеим сторонам (тот же порядок, что у приостановки подписки).
    """
    clean_reason = (reason or "").strip()
    if not clean_reason:
        return None, "REASON_REQUIRED"
    if not company.is_active:
        return None, "COMPANY_ALREADY_ARCHIVED"

    company.is_active = False
    company.archived_at = timezone.now()
    company.archived_by = actor
    company.archived_reason = clean_reason
    company.save(update_fields=["is_active", "archived_at", "archived_by", "archived_reason"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="company",
        entity_id=company.id,
        action="Компания архивирована",
        detail=f"{company.name}: выведена из оборота",
        # Префикс `admin.` обязателен: по нему «Журнал доступа» отбирает операторские
        # действия. Без него запись существует, но оператор её не увидит (волна #597).
        event_code="admin.company.archived",
        event_params={"company_name": company.name},
        actor=actor,
        reason=clean_reason,
        before={"is_active": True},
        after={"is_active": False},
        level="WARNING",
        company_id=company.id,
    )
    return company, None


@transaction.atomic
def unarchive_company(company: Company, actor: CustomUser) -> Tuple[Optional[Company], Optional[str]]:
    """Вернуть компанию в оборот. Обратимость — половина смысла архива (Odoo unarchive)."""
    if company.is_active:
        return None, "COMPANY_NOT_ARCHIVED"

    company.is_active = True
    company.archived_at = None
    company.archived_by = None
    company.archived_reason = ""
    company.save(update_fields=["is_active", "archived_at", "archived_by", "archived_reason"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="company",
        entity_id=company.id,
        action="Компания возвращена в оборот",
        detail=f"{company.name}: архив снят",
        event_code="admin.company.unarchived",
        event_params={"company_name": company.name},
        actor=actor,
        before={"is_active": False},
        after={"is_active": True},
        level="INFO",
        company_id=company.id,
    )
    return company, None
