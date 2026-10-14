"""
«Режим только чтения» в инженерной админке закрывает и то, что раньше пропускал.

Замеры скептиков 25-08 (находки 60, 61, 62, 64 прогона 20-08):

* **61.** `ReadOnlyInspectionMixin` вычёркивал M2M из списка полей, которые делает readonly.
  У инженера с `change_company` на форме компании оставалось РОВНО ОДНО живое поле — `types`:
  снятие `SUPPLIER` выбивало компанию из подбора продавцов у всех покупателей. Докстринг
  обещал «all fields become readonly».
* **60.** У массовых действий `django_celery_beat` `allowed_permissions = None`, поэтому право
  `view_periodictask` открывало ЗАПИСЬ: одним POST'ом выключалась платформенная задача — без
  подтверждения и без следа. Молча гаснут автосинк ТН ВЭД, напоминания об оплате, истечение
  подписок.
* **62.** `EmailTemplateAdmin` — единственная админка своего файла без readonly-миксина.
* **64.** Код справочника переписывался через API как обычное поле, хотя по нему сравнивается
  логика (Rule 2). В админке зазора не было — там код закрыт общим режимом инспекции.

Проверяем ПОВЕДЕНИЕ (набор readonly-полей и результат действия), а не наличие миксина в
цепочке классов: наследование можно сохранить и всё равно оставить дыру.
"""

import pytest
from django.contrib import admin
from django.contrib.auth.models import Group, Permission

from accounts.models import Company, CustomUser
from notifications.models import EmailTemplate


class _Request:
    def __init__(self, user):
        self.user = user
        self.GET = {}


@pytest.fixture
def engineer(db):
    """Каноничный инженер: в группе `system_engineers`, но не суперпользователь."""
    user = CustomUser.objects.create_user(
        email="engineer@readonly.test",
        username="engineer_readonly",
        password="x",
        is_staff=True,
        is_active=True,
    )
    group, _ = Group.objects.get_or_create(name="system_engineers")
    user.groups.add(group)
    return user


@pytest.fixture
def superuser(db):
    return CustomUser.objects.create_user(
        email="root@readonly.test",
        username="root_readonly",
        password="x",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )


def _readonly_for(model, user, obj):
    model_admin = admin.site._registry[model]
    return set(model_admin.get_readonly_fields(_Request(user), obj=obj))


# ── 61. M2M больше не проходит мимо режима только чтения ────────────────────


def test_company_types_are_readonly_for_an_engineer(engineer, db):
    """Снятие типа SUPPLIER выбивало компанию из подбора продавцов у ВСЕХ покупателей."""
    company = Company.objects.create(name="Компания M2M", inn="908100001")

    readonly = _readonly_for(Company, engineer, company)

    assert "types" in readonly, "M2M обязан быть закрыт: это роль компании на рынке"
    assert "inn" in readonly, "опорная проверка: обычные поля закрыты и раньше"


def test_the_superuser_still_edits_everything(superuser, db):
    """Обратная сторона: у суперпользователя полные права — решение владельца 2026-06-29."""
    company = Company.objects.create(name="Компания супера", inn="908100003")

    readonly = _readonly_for(Company, superuser, company)

    assert "types" not in readonly
    assert "inn" not in readonly


def test_reverse_relations_are_not_declared_readonly(engineer, db):
    """`one_to_many` исключается по-прежнему: это не поля формы, и Django падает, если
    объявить их readonly."""
    company = Company.objects.create(name="Обратные связи", inn="908100004")

    readonly = _readonly_for(Company, engineer, company)

    assert "members" not in readonly
    assert "contacts" not in readonly


# ── 62. Шаблоны писем под тем же режимом ────────────────────────────────────


def test_email_template_body_is_readonly_for_an_engineer(engineer, db):
    """Активная строка немедленно подменяет файловый шаблон ДЛЯ ВСЕХ получателей платформы."""
    template = EmailTemplate.objects.create(key="quote_sent", subject="Тема", html_body="<p>текст</p>")

    readonly = _readonly_for(EmailTemplate, engineer, template)

    assert "html_body" in readonly
    assert "subject" in readonly


def test_email_template_cannot_be_deleted_by_an_engineer(engineer, db):
    template = EmailTemplate.objects.create(key="reset_password", subject="Тема", html_body="<p>текст</p>")
    model_admin = admin.site._registry[EmailTemplate]

    assert model_admin.has_delete_permission(_Request(engineer), obj=template) is False
    assert model_admin.has_add_permission(_Request(engineer)) is False


# ── 60. Расписание Celery: право на просмотр не даёт записи ─────────────────


def test_beat_bulk_actions_are_hidden_from_a_non_superuser(engineer, db):
    """У действий библиотеки `allowed_permissions = None` — Django их правами НЕ фильтрует,
    поэтому право на просмотр открывало запись."""
    from django_celery_beat.models import PeriodicTask

    model_admin = admin.site._registry[PeriodicTask]
    engineer.user_permissions.add(Permission.objects.get(codename="view_periodictask"))

    actions = model_admin.get_actions(_Request(engineer))

    assert actions == {}, f"не-суперпользователю не предлагается ни одного действия: {list(actions)}"


def test_beat_schedule_is_readonly_for_a_non_superuser(engineer, db):
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    # Задаче обязательно нужно расписание — библиотека валидирует это на сохранении.
    schedule = IntervalSchedule.objects.create(every=1, period=IntervalSchedule.DAYS)
    task = PeriodicTask.objects.create(name="probe-task", task="core.noop", interval=schedule)
    model_admin = admin.site._registry[PeriodicTask]

    readonly = set(model_admin.get_readonly_fields(_Request(engineer), obj=task))

    assert "enabled" in readonly, "выключение задачи гасит платформенный механизм"
    assert model_admin.has_delete_permission(_Request(engineer), obj=task) is False


def test_the_superuser_keeps_beat_actions(superuser, db):
    from django_celery_beat.models import PeriodicTask

    model_admin = admin.site._registry[PeriodicTask]

    assert model_admin.get_actions(_Request(superuser)), "инструмент инженера остаётся"


# ── 64. Код справочника — стабильный ключ, а не текст ───────────────────────


def test_lookup_code_cannot_be_renamed_through_the_api(db):
    """Замер скептика поправил находку: в АДМИНКЕ код и так закрыт общим режимом инспекции —
    у не-суперпользователя readonly накрывает все поля. Живой зазор был в API: `PATCH` с полем
    `code` проходил как обычная правка, и ветки в сервисах, спрашивающие прежний код, тихо
    переставали срабатывать (Rule 2 — логика сравнивается по коду)."""
    from rest_framework.test import APIClient

    from accounts.models import SystemRole
    from master_data.models import UnitOfMeasure

    unit = UnitOfMeasure.objects.create(code="PROBE_UOM", name="Проба", sort_order=900)
    operator = CustomUser.objects.create_user(
        is_superuser=True,
        email="lookups@readonly.test",
        username="lookups_readonly",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=operator)

    resp = client.patch(
        f"/api/v1/master-data/units/{unit.pk}/", {"code": "RENAMED", "name": "Новое имя"}, format="json"
    )

    assert resp.status_code == 200, resp.content
    unit.refresh_from_db()
    assert unit.code == "PROBE_UOM", "код обязан устоять"
    assert unit.name == "Новое имя", "остальные поля правятся как прежде — это не запрет правки"


def test_a_new_lookup_still_sets_its_code(db):
    """Обратная сторона: завести НОВЫЙ код можно — закрыто только переписывание старого."""
    from rest_framework.test import APIClient

    from accounts.models import SystemRole
    from master_data.models import UnitOfMeasure

    operator = CustomUser.objects.create_user(
        is_superuser=True,
        email="lookups2@readonly.test",
        username="lookups2_readonly",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=operator)

    resp = client.post(
        "/api/v1/master-data/units/", {"code": "BRAND_NEW", "name": "Новая единица", "sort_order": 901}, format="json"
    )

    assert resp.status_code == 201, resp.content
    assert UnitOfMeasure.objects.get(code="BRAND_NEW").name == "Новая единица"
