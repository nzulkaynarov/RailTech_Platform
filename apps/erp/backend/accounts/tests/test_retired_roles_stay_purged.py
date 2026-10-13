"""Отставные системные роли не воскресают — независимо от порядка миграций.

ADR-0002 сузил `SystemRole` до ADMIN/USER, но `core/0002_seed_enterprise_lookups` продолжает
сеять старый набор, а зависимости между ним и пургом (`accounts/0019`) объявлено не было.
На боевой базе порядок сложился удачно, на свежей — нет: роли возвращались, и оператор видел
в реестре пользователей вкладки-фильтры `roles.GUEST`, `roles.CLIENT` и прочие, подписанные
сырыми ключами (переводов нет, потому что роли выведены). Найдено прогоном глазами 19-08.

Тест смотрит на СОСТОЯНИЕ БАЗЫ после всех миграций — то есть ровно на то, что видит оператор,
а не на текст конкретной миграции.
"""

import pytest

from accounts.models import SystemRole

RETIRED = {"GUEST", "CLIENT", "EMPLOYEE", "ACCOUNT_MANAGER", "SALES_MANAGER", "MANUFACTURER"}


@pytest.mark.django_db
def test_only_canonical_system_roles_exist():
    codes = set(SystemRole.objects.values_list("code", flat=True))
    assert codes <= {"ADMIN", "USER"}, f"в базе воскресли выведенные роли: {sorted(codes - {'ADMIN', 'USER'})}"


@pytest.mark.django_db
def test_no_retired_role_survives_migrations():
    survivors = set(SystemRole.objects.filter(code__in=RETIRED).values_list("code", flat=True))
    assert not survivors, f"выведенные роли остались в базе: {sorted(survivors)}"


@pytest.mark.django_db
def test_canonical_roles_are_present():
    """Обратная сторона: пург не должен унести рабочие роли — на них стоит вся авторизация."""
    codes = set(SystemRole.objects.values_list("code", flat=True))
    assert {"ADMIN", "USER"} <= codes, f"пропали канонические роли, есть только: {sorted(codes)}"
