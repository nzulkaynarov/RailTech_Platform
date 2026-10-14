"""
Аварийные действия инженера подтверждаются и оставляют след (находка 63 прогона 20-08).

Замер 25-08 по девяти обработчикам `@superuser_only_action`:

* **Ни одного экрана подтверждения.** Действие срабатывало с первого клика: выбрал 42 компании,
  промахнулся в выпадающем списке, нажал «Выполнить» — и все 42 изменились разом. Django ровно
  для такого случая показывает промежуточный экран (`delete_selected_confirmation`).
* **Пять из девяти не писали журнал вовсе** (публикация товаров, одобрение и отклонение заявок
  на роль, активация и приостановка подписки).
* **Ни одно не попадало в «Журнал доступа»**: тот отбирает по машинному коду `admin.*`
  (`event_code` с префиксом `admin.`), а свободные записи сервисов его не несут. Инженер правил
  данные арендаторов, и увидеть это можно было в трёх разных местах или нигде.

(Аварийные действия над подписками удалены вместе с монетизацией в M1-ERP-02 волна 2.)

Чиним в ОДНОМ месте — обёртке `superuser_only_action`, а не в девяти обработчиках.

Обёртку проверяем на аварийном «Закрыть как проигранную» по сделкам (раньше — на аварийном
подтверждении KYC компаний; KYC удалён в M1-ERP-02 волна 1c).
"""

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.urls import reverse

from accounts.models import Company, CustomUser
from crm.models import ActivityLog, Deal, DealStage


@pytest.fixture
def engineer(db):
    """Суперпользователь — единственный, кому аварийные действия вообще предлагаются."""
    return CustomUser.objects.create_user(
        email="root@emergency.test",
        username="root_emergency",
        password="Probe1234!",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )


@pytest.fixture
def deals(db):
    """Открытые сделки (DRAFT) — аварийное действие закрывает их как проигранные."""
    draft = DealStage.objects.get(code="DRAFT")
    rows = []
    for index in range(2):
        company = Company.objects.create(name=f"Компания {index}", inn=f"90820000{index}")
        rows.append(Deal.objects.create(title=f"Аварийная сделка {index}", company=company, stage=draft))
    return rows


def _post_action(client, deals, action="mark_closed_lost", **extra):
    url = reverse(f"admin:{Deal._meta.app_label}_deal_changelist")
    payload = {
        "action": action,
        ACTION_CHECKBOX_NAME: [str(deal.pk) for deal in deals],
        **extra,
    }
    return client.post(url, payload, follow=False)


def _stage(deal) -> str:
    deal.refresh_from_db()
    return deal.stage.code


# ── Первый клик показывает, что будет затронуто ─────────────────────────────


def test_the_first_click_only_asks(client, engineer, deals):
    """Действие затрагивало строки СРАЗУ. Теперь первый клик — вопрос, а не выполнение."""
    client.force_login(engineer)

    resp = _post_action(client, deals)

    assert resp.status_code == 200, "промежуточный экран, а не редирект после выполнения"
    for deal in deals:
        assert _stage(deal) == "DRAFT", "до подтверждения не меняется НИЧЕГО"


def test_the_confirmation_names_every_affected_row(client, engineer, deals):
    """Смысл экрана — показать, ЧТО именно затронет действие: иначе он просто лишний клик."""
    client.force_login(engineer)

    body = _post_action(client, deals).content.decode()

    for deal in deals:
        assert deal.title in body


def test_a_reason_is_required(client, engineer, deals):
    """Подтверждение без причины действие не выполняет — аварийное вмешательство без
    обоснования неотличимо от промаха мышью."""
    client.force_login(engineer)

    resp = _post_action(client, deals, _emergency_confirmed="1", _emergency_reason="   ")

    assert resp.status_code == 200, "снова экран подтверждения, а не выполнение"
    for deal in deals:
        assert _stage(deal) == "DRAFT"


def test_the_confirmed_action_really_runs(client, engineer, deals):
    """Обратная сторона: подтверждённое действие выполняется — инструмент инженера остался."""
    client.force_login(engineer)

    _post_action(client, deals, _emergency_confirmed="1", _emergency_reason="Инцидент INC-42")

    for deal in deals:
        assert _stage(deal) == "CLOSED_LOST"


# ── След в журнале доступа ──────────────────────────────────────────────────


def test_every_affected_row_lands_in_the_access_log(client, engineer, deals):
    """Отбор журнала доступа идёт по машинному коду `admin.*` — свободный текст сервиса в него
    не попадал, и аварийного вмешательства там не было видно вовсе."""
    client.force_login(engineer)

    _post_action(client, deals, _emergency_confirmed="1", _emergency_reason="Инцидент INC-42")

    entries = ActivityLog.objects.filter(event_code__startswith="admin.emergency.")
    assert entries.count() == len(deals), "по записи на каждую затронутую строку"
    assert set(entries.values_list("entity_id", flat=True)) == {deal.pk for deal in deals}


def test_the_reason_and_the_actor_are_stored(client, engineer, deals):
    client.force_login(engineer)

    _post_action(client, deals, _emergency_confirmed="1", _emergency_reason="Инцидент INC-42")

    entry = ActivityLog.objects.filter(event_code__startswith="admin.emergency.").first()
    assert entry.reason == "Инцидент INC-42"
    assert entry.user_id == engineer.pk
    assert entry.level == "WARNING"


def test_the_entry_matches_the_access_log_filter(client, engineer, deals):
    """Проверяем ТЕМ ЖЕ условием, каким отбирает экран журнала доступа, а не своим:
    собственное условие в тесте зелёное даже тогда, когда экран пуст."""
    from django.db.models import Q

    client.force_login(engineer)
    _post_action(client, deals, _emergency_confirmed="1", _emergency_reason="Инцидент INC-42")

    visible = ActivityLog.objects.filter(
        Q(expires_at__isnull=False) | Q(action__icontains="[FORCE_ADMIN]") | Q(event_code__startswith="admin.")
    )

    assert visible.count() >= len(deals)


def test_a_handler_that_deletes_rows_still_leaves_a_trace(client, engineer, db):
    """Строки снимаются ДО вызова обработчика: `archive_selected` удаляет сообщения, и после
    него набора уже нет — журнал вышел бы пустым ровно там, где он нужнее всего."""
    from core.admin_mixins import _log_emergency_action

    company = Company.objects.create(name="Исчезающая", inn="908200099")
    affected = [(company.pk, company.name)]
    company.delete()

    class _Request:
        user = engineer

    _log_emergency_action(_Request(), Company, affected, "archive_selected", "[Emergency] Архивировать", "причина")

    entry = ActivityLog.objects.get(event_code="admin.emergency.archive_selected")
    assert "Исчезающая" in entry.action


# ── Не-суперпользователю ничего не предлагается ─────────────────────────────


def test_a_non_superuser_is_still_refused(client, db, deals):
    staff = CustomUser.objects.create_user(
        email="staff@emergency.test",
        username="staff_emergency",
        password="Probe1234!",
        is_staff=True,
        is_active=True,
    )
    from django.contrib.auth.models import Permission

    staff.user_permissions.add(Permission.objects.get(codename="view_deal"))
    staff.user_permissions.add(Permission.objects.get(codename="change_deal"))
    client.force_login(staff)

    _post_action(client, deals, _emergency_confirmed="1", _emergency_reason="попытка")

    for deal in deals:
        assert _stage(deal) == "DRAFT"
    assert not ActivityLog.objects.filter(event_code__startswith="admin.emergency.").exists()
