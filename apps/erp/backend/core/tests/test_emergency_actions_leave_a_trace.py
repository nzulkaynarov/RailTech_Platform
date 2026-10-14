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

Плюс к тому аварийная приостановка подписки шла мимо оповещения арендатора: панель оператора
звала сервис и слала письмо, аварийный люк писал статус сырым `update()` и молчал.

Чиним в ОДНОМ месте — обёртке `superuser_only_action`, а не в девяти обработчиках.

Обёртку проверяем на аварийном «Закрыть как проигранную» по сделкам (раньше — на аварийном
подтверждении KYC компаний; KYC удалён в M1-ERP-02 волна 1c).
"""

from datetime import timedelta

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SupplierSubscription, WorkspaceRole
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
    url = reverse("admin:crm_deal_changelist")
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


# ── Аварийная приостановка доходит до арендатора ────────────────────────────


def test_emergency_suspension_notifies_the_tenant(client, engineer, db, django_capture_on_commit_callbacks):
    """Дверей было две: панель оператора звала сервис и слала письмо, аварийный люк писал
    статус сырым `update()` и молчал."""
    from notifications.models import EmailLog

    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    company = Company.objects.create(
        name="Отключаемый через люк",
        inn="908200100",
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    # Письмо адресуется человеку, а не компании: без владельца отправлять его некому, и тест
    # был бы зелёным на сломанном коде ровно по этой причине.
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    owner = CustomUser.objects.create_user(
        email="owner@emergency.test", username="owner_emergency", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=owner,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    subscription = SupplierSubscription.objects.create(
        company=company,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=90),
    )
    client.force_login(engineer)
    before = EmailLog.objects.count()

    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            reverse("admin:accounts_suppliersubscription_changelist"),
            {
                "action": "suspend_subscription",
                ACTION_CHECKBOX_NAME: [str(subscription.pk)],
                "_emergency_confirmed": "1",
                "_emergency_reason": "Инцидент INC-43",
            },
        )

    subscription.refresh_from_db()
    assert subscription.status == "SUSPENDED"
    assert subscription.suspended_reason == "Инцидент INC-43", "причина обязана дойти до арендатора"
    assert EmailLog.objects.count() > before, "письмо уходит и из аварийного люка"
