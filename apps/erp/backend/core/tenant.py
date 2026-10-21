"""Своя компания — компания-владелец ERP (BUSINESS §3.3: «ERP не является маркетплейсом: продавец один»).

Одна точка истины для всех мест, где раньше продавец сделки выводился из маршрутизации заявок
между продавцами (удалена в M1-ERP-02 волна 3): продавец любой сделки, КП, договора, счёта и
акта — эта компания; сотрудники бэк-офиса — её активные участники.

Как определяется:

1. Настройка `OWN_COMPANY_ID` (переменная окружения) — явный выбор; нужна, только если в
   базе больше одной компании-продавца с участниками (например, после переноса данных B2B, M5-ERP-01).
2. Иначе — единственная активная компания-продавец (`Company.objects.sellers()`) хотя бы с одним
   активным участником. Так работают dev, тесты и свежий стенд: фикстура создаёт одну такую компанию.
3. Нет ни одной — `None`: в ERP ещё нет сотрудников, действует только администратор (`is_superuser`);
   он создаёт компанию мастером первого запуска (`accounts.services.own_company_setup`, FIX-65).
   Больше одной без настройки — `ImproperlyConfigured`: угадывать продавца нельзя (ошибка громкая,
   а не тихий отказ всем сотрудникам).

Результат не кэшируется: один короткий запрос, а кэш между тестами и после правки компаний
давал бы устаревший ответ.
"""

from typing import Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def own_company_id() -> Optional[int]:
    """Id компании-владельца или None (сотрудников ещё нет)."""
    configured = getattr(settings, "OWN_COMPANY_ID", None)
    if configured:
        return int(configured)
    from accounts.models import Company

    candidate_ids = list(
        Company.objects.sellers().filter(members__is_active=True).order_by("id").values_list("id", flat=True)[:2]
    )
    if len(candidate_ids) > 1:
        raise ImproperlyConfigured(
            "OWN_COMPANY_ID is not set and more than one seller company has active members — "
            "set OWN_COMPANY_ID to the company that owns this ERP."
        )
    return candidate_ids[0] if candidate_ids else None


def own_company():
    """Компания-владелец (`accounts.Company`) или None."""
    company_id = own_company_id()
    if company_id is None:
        return None
    from accounts.models import Company

    return Company.objects.filter(pk=company_id).first()
