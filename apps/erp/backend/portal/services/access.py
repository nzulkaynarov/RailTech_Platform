"""Кому открыт кабинет: компания «в обороте» и либо клиент, либо партнёр с отношением (FIX-15, K0, ADR-0022).

Архив обязан снимать компанию со ВСЕХ поверхностей разом (см. `parties.models.core.active_company_q`), поэтому
вход, обмен ссылки, приглашение и проверка живой сессии спрашивают его здесь, а не читают `Company.is_active`.

Правило (одно место; мест, где оно записано иначе, быть не должно):

* **клиент** — среди типов компании есть `CLIENT` (K0, решение владельца 2026-11-01; сигнал «SUPPLIER ⇒ CLIENT»
  удалён, `accounts/signals.py`) и это не своя компания; клиенты на отношения не переводятся;
* **партнёр** (изготовитель, поставщик, принципал) — у компании есть отношение `partner` (`parties.CompanyRelationship`)
  в статусе «приглашён» (на время первого входа) или «активен»; приостановленное отношение закрывает вход, а живые сессии
  гаснут на следующем запросе. Что открыто партнёру, решают включённые на отношении модули (`portal/services/roles.py`);
* своя компания (владелец ERP) в кабинет не входит ни ролью.

`company_has_cabinet_access` отвечает для одной компании, `cabinet_company_q` — для выборок, `company_access` называет
роли и модули, по которым сессия получает меню кабинета и доступ к эндпоинтам. Роли складываются (клиент и партнёр).
"""

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Exists, ExpressionWrapper, OuterRef, Subquery
from django.utils import timezone
from parties.models import Company, CompanyRelationship, RelationshipRole, RelationshipStatus, active_company_q
from parties.models.relationships import ENTRY_STATUSES
from portal.services.roles import modules_for

from accounts.constants import CompanyTypeCode
from core.tenant import own_company_id


def _own_company_id() -> int | None:
    """Id своей компании или `None` (её нет или определить нельзя: тогда решает тип, вход клиентов не ломаем)."""
    try:
        return own_company_id()
    except ImproperlyConfigured:
        return None


def _not_own_q(prefix: str) -> models.Q:
    own_id = _own_company_id()
    if own_id is None:
        return models.Q()
    return ~models.Q(**{f"{prefix}__pk" if prefix else "pk": own_id})


def _outer_pk(prefix: str) -> OuterRef:
    return OuterRef(f"{prefix}__pk" if prefix else "pk")


def _client_q(prefix: str) -> models.Q:
    """Среди типов компании есть CLIENT. Подзапрос по таблице связи, а не JOIN: строки выборки не размножаются."""
    return models.Q(
        Exists(
            Company.types.through.objects.filter(company_id=_outer_pk(prefix), companytype__code=CompanyTypeCode.CLIENT)
        )
    )


def _partner_q(prefix: str) -> models.Q:
    """Есть отношение `partner`, открывающее вход (приглашён или активен)."""
    return models.Q(
        Exists(
            CompanyRelationship.objects.filter(
                company_id=_outer_pk(prefix), role=RelationshipRole.PARTNER, status__in=ENTRY_STATUSES
            )
        )
    )


def cabinet_company_q(prefix: str = "") -> models.Q:
    """Предикат «компания допущена в кабинет»: в обороте, не своя, и она клиент или партнёр с отношением.

    `prefix` — путь до Company от фильтруемой модели (`cabinet_company_q("company")` для Contact/PortalSession).
    """
    return active_company_q(prefix) & _not_own_q(prefix) & (_client_q(prefix) | _partner_q(prefix))


def client_company_q(prefix: str = "") -> models.Q:
    """Компания допущена в кабинет как клиент (роль `client`)."""
    return active_company_q(prefix) & _not_own_q(prefix) & _client_q(prefix)


def partner_company_q(prefix: str = "") -> models.Q:
    """Компания допущена в кабинет как партнёр (роль `partner`)."""
    return active_company_q(prefix) & _not_own_q(prefix) & _partner_q(prefix)


#: Имена аннотаций ролей и модулей: сессию, её роли и модули партнёра читает один запрос (`PortalAuthentication`).
ROLE_FLAGS = {RelationshipRole.CLIENT.value: "portal_is_client", RelationshipRole.PARTNER.value: "portal_is_partner"}
PARTNER_MODULES_FIELD = "portal_partner_modules"


def role_annotations(prefix: str = "") -> dict:
    """Аннотации ролей и включённых партнёру модулей для выборки по Company (или по модели с путём `prefix`)."""
    partner_modules = Subquery(
        CompanyRelationship.objects.filter(
            company_id=_outer_pk(prefix), role=RelationshipRole.PARTNER, status__in=ENTRY_STATUSES
        ).values("modules")[:1],
        output_field=models.JSONField(),
    )
    return {
        ROLE_FLAGS[RelationshipRole.CLIENT.value]: ExpressionWrapper(client_company_q(prefix), models.BooleanField()),
        ROLE_FLAGS[RelationshipRole.PARTNER.value]: ExpressionWrapper(partner_company_q(prefix), models.BooleanField()),
        PARTNER_MODULES_FIELD: partner_modules,
    }


def access_from_row(row) -> tuple[list[str], list[str]]:
    """Роли и модули из объекта с аннотациями `role_annotations` (порядок ролей стабилен: `client`, затем `partner`)."""
    roles = [role for role, flag in ROLE_FLAGS.items() if getattr(row, flag, False)]
    return roles, modules_for(roles, getattr(row, PARTNER_MODULES_FIELD, None))


def company_in_circulation(company_id: int | None) -> bool:
    """Компания существует и не в архиве."""
    if company_id is None:
        return False
    return Company.objects.filter(active_company_q(), pk=company_id).exists()


def company_has_cabinet_access(company_id: int | None) -> bool:
    """Компании открыт кабинет: не в архиве, не своя, и она клиент либо партнёр с действующим отношением."""
    if company_id is None:
        return False
    return Company.objects.filter(cabinet_company_q(), pk=company_id).exists()


def company_access(company_id: int | None) -> tuple[list[str], list[str]]:
    """Роли и модули компании в кабинете; пусто — кабинет закрыт."""
    if company_id is None:
        return [], []
    row = Company.objects.filter(pk=company_id).annotate(**role_annotations()).first()
    return access_from_row(row) if row is not None else ([], [])


def company_roles(company_id: int | None) -> list[str]:
    return company_access(company_id)[0]


def activate_on_first_login(company_id: int | None) -> None:
    """Первый вход приглашённого партнёра переводит его отношение `invited → active` (приостановленное не трогает).

    Если у компании есть открытая заявка кандидата в партнёры (submitted, contract_sent, candidate_agreed),
    отношение не активируется до финального одобрения директором.
    """
    if company_id is None:
        return
    from parties.models import PartnerApplication, PartnerApplicationStatus

    has_pending_app = PartnerApplication.objects.filter(
        company_id=company_id,
        status__in=[
            PartnerApplicationStatus.SUBMITTED,
            PartnerApplicationStatus.CONTRACT_SENT,
            PartnerApplicationStatus.CANDIDATE_AGREED,
        ],
    ).exists()
    if has_pending_app:
        return

    CompanyRelationship.objects.filter(
        company_id=company_id, role=RelationshipRole.PARTNER, status=RelationshipStatus.INVITED
    ).update(status=RelationshipStatus.ACTIVE, activated_at=timezone.now(), updated_at=timezone.now())
