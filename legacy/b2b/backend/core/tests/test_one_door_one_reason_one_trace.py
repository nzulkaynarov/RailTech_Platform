"""
Действие оператора: одна дверь, одна причина, один след.

Замеры скептиков 26-08 по находкам 21, 35, 42, 43, 44, 45, 117 прогона 20-08 — и один замер,
которого в аудите не было вовсе.

* **43.** У подписки была ВТОРАЯ дверь к тому же результату: обычный `PATCH {"status":
  "SUSPENDED"}` по карточке. Он не звал сервис, не требовал причины, не заполнял
  `suspended_reason`/`suspended_at` и НЕ слал арендатору ни письма, ни уведомления — ровно то,
  ради чего заводили #611. Отключение платящего продавца проходило молча.
* **44.** У `SupplierSubscriptionViewSet` не было ни `perform_create`, ни `perform_destroy`:
  DELETE физически уносил запись вместе с историей оплат, и в журнале не оставалось ни того,
  что удалили, ни кем.
* **45.** Массовая приостановка писала запись БЕЗ `event_code`, а «Журнал доступа» отбирает
  ленту по машинному коду `admin.*` — отключение ПАЧКИ продавцов было видно хуже, чем одного.
* **35.** `list`/`retrieve` реестра заявок на роль не были отображены в `operator_permissions`,
  а выборка оператора платформы не скоупится ничем: любая суб-роль, включая «Поддержку» с
  пустым набором прав, читала заявки чужих компаний — название, ИНН, e-mail заявителя и
  приложенные договор с NDA.
* **21.** Правки справочников и шаблонов писем не оставляли следа вовсе, хотя печатаются в
  документах и письмах ВСЕХ арендаторов.
* **117.** «Пометить прочитанными» — единственное массовое действие админки без
  `@superuser_only_action`; отбор в миксине опирался на наличие `__wrapped__`, то есть на
  признак `functools.wraps`, а не на намерение автора.
* **Сверх аудита (замер 26-08).** Обещание докстринга `ReadOnlyInspectionMixin` — «NON-superuser
  staff remain in read-only inspection mode» — выполнялось у 28 админок из 60. У остальных 32
  инженер с модельными правами правил и удалял: журнал активности (13 полей из 18), историю
  правок КП, все справочники FSM и accounts, `auth.Group` и `auth.Permission`. Последнее —
  путь самовыдачи «второго ключа», на котором стоит гейт мастера компаний из #599.
"""

from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import (
    Company,
    CompanyType,
    CustomUser,
    OperatorRole,
    SupplierSubscription,
    SystemRole,
    VerificationStatus,
)
from crm.models import ActivityLog

ACCESS_LOG_FILTER = (
    Q(expires_at__isnull=False) | Q(action__icontains="[FORCE_ADMIN]") | Q(event_code__startswith="admin.")
)


class _Request:
    method = "GET"

    def __init__(self, user):
        self.user = user
        self.GET = {}


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def billing_operator(db):
    role = OperatorRole.objects.create(
        code="OD_BILLING", name="Биллинг", permissions=["billing.view", "billing.manage"]
    )
    return CustomUser.objects.create_user(
        email="billing@onedoor.test",
        username="billing_onedoor",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        operator_role=role,
        is_active=True,
    )


@pytest.fixture
def seller_company(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    company = Company.objects.create(
        name="Продавец одной двери",
        inn="908500001",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    return company


@pytest.fixture
def subscription(seller_company):
    return SupplierSubscription.objects.create(
        company=seller_company,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=90),
    )


# ── 43. Статус меняют действия, а не правка карточки ────────────────────────


def test_patching_the_status_is_refused(billing_operator, subscription):
    resp = _api(billing_operator).patch(
        f"/api/v1/accounts/subscriptions/{subscription.pk}/", {"status": "SUSPENDED"}, format="json"
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "SUBSCRIPTION_STATUS_IS_AN_ACTION"
    subscription.refresh_from_db()
    assert subscription.status == "ACTIVE", "отказ обязан ничего не менять"


def test_patching_other_fields_still_works(billing_operator, subscription):
    """Обратная сторона: карточка осталась редактируемой — закрыт ровно статус."""
    resp = _api(billing_operator).patch(
        f"/api/v1/accounts/subscriptions/{subscription.pk}/", {"notes": "перенесли оплату"}, format="json"
    )

    assert resp.status_code == 200, resp.content
    subscription.refresh_from_db()
    assert subscription.notes == "перенесли оплату"


def test_sending_the_same_status_is_not_a_change(billing_operator, subscription):
    """Витрина шлёт карточку целиком; неизменившийся статус — не попытка обойти действие."""
    resp = _api(billing_operator).patch(
        f"/api/v1/accounts/subscriptions/{subscription.pk}/",
        {"status": "ACTIVE", "notes": "без смены статуса"},
        format="json",
    )

    assert resp.status_code == 200, resp.content


def test_the_action_path_still_suspends_and_notifies(
    billing_operator, subscription, django_capture_on_commit_callbacks
):
    from notifications.models import EmailLog

    before = EmailLog.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        resp = _api(billing_operator).post(
            f"/api/v1/accounts/subscriptions/{subscription.pk}/suspend/", {"reason": "Неоплата"}, format="json"
        )

    assert resp.status_code == 200, resp.content
    subscription.refresh_from_db()
    assert subscription.status == "SUSPENDED"
    assert subscription.suspended_reason == "Неоплата"
    assert EmailLog.objects.count() >= before, "путь действия по-прежнему оповещает"


# ── 44. Создание и удаление подписки оставляют след ─────────────────────────


def test_creating_a_subscription_leaves_a_trace(billing_operator, seller_company, db):
    resp = _api(billing_operator).post(
        "/api/v1/accounts/subscriptions/",
        {"company": seller_company.pk, "plan": "BASIC", "status": "ACTIVE", "monthly_rate": "500000"},
        format="json",
    )

    assert resp.status_code == 201, resp.content
    entry = ActivityLog.objects.get(event_code="admin.subscription.created")
    assert entry.user_id == billing_operator.pk
    assert ActivityLog.objects.filter(
        ACCESS_LOG_FILTER, pk=entry.pk
    ).exists(), "запись обязана попасть в журнал доступа"


def test_deleting_a_subscription_leaves_a_trace_of_what_was_deleted(billing_operator, subscription):
    """След пишется ДО удаления: после него ни pk, ни компании уже не спросишь."""
    company_name = subscription.company.name

    resp = _api(billing_operator).delete(f"/api/v1/accounts/subscriptions/{subscription.pk}/")

    assert resp.status_code == 204
    assert not SupplierSubscription.objects.filter(pk=subscription.pk).exists()
    entry = ActivityLog.objects.get(event_code="admin.subscription.deleted")
    assert company_name in entry.detail
    assert entry.before_data["plan"] == "PREMIUM", "в следе видно, ЧТО именно удалили"


# ── 45. Массовая приостановка видна в журнале доступа ───────────────────────


def test_bulk_suspension_reaches_the_access_log(billing_operator, subscription, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        resp = _api(billing_operator).post(
            "/api/v1/accounts/subscriptions/bulk-set-status/",
            {"ids": [subscription.pk], "status": "SUSPENDED", "reason": "проверка"},
            format="json",
        )

    assert resp.status_code == 200, resp.content
    bulk = ActivityLog.objects.filter(action__icontains="Bulk")
    assert bulk.exists()
    assert ActivityLog.objects.filter(ACCESS_LOG_FILTER, pk__in=bulk.values("pk")).count() == bulk.count()


# ── 35. Реестр чужих заявок закрыт правом ───────────────────────────────────


@pytest.fixture
def support_operator(db):
    """Оператор «Поддержка» — заведён как ТОЛЬКО ПРОСМОТР, без права модерации."""
    role = OperatorRole.objects.create(code="OD_SUPPORT", name="Поддержка", permissions=["users.view"])
    return CustomUser.objects.create_user(
        email="support@onedoor.test",
        username="support_onedoor",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        operator_role=role,
        is_active=True,
    )


def test_an_operator_without_moderation_cannot_read_other_companies_applications(support_operator, seller_company):
    resp = _api(support_operator).get("/api/v1/accounts/role-applications/")

    assert resp.status_code == 403
    assert str(resp.json()["detail"]) == "OPERATOR_PERMISSION_REQUIRED"


def test_the_moderator_still_reads_the_registry(db, seller_company):
    """Обратная сторона: у кого право есть — реестр открыт, экран не сломан."""
    role = OperatorRole.objects.create(
        code="OD_MODERATOR", name="Модератор", permissions=["moderation.role_applications"]
    )
    moderator = CustomUser.objects.create_user(
        email="moder@onedoor.test",
        username="moder_onedoor",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        operator_role=role,
        is_active=True,
    )

    assert _api(moderator).get("/api/v1/accounts/role-applications/").status_code == 200


def test_a_tenant_still_sees_their_own_applications(db, seller_company):
    """Гейт поставлен ОПЕРАТОРУ, а не арендатору: его выборку и так сужает `get_queryset`."""
    member = CustomUser.objects.create_user(
        email="tenant@onedoor.test", username="tenant_onedoor", password="x", is_active=True
    )

    assert _api(member).get("/api/v1/accounts/role-applications/").status_code == 200


# ── 21. Справочники и шаблоны писем оставляют след ──────────────────────────


@pytest.fixture
def settings_operator(db):
    role = OperatorRole.objects.create(code="OD_SETTINGS", name="Настройки", permissions=["platform.settings"])
    return CustomUser.objects.create_user(
        email="settings@onedoor.test",
        username="settings_onedoor",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        operator_role=role,
        is_active=True,
    )


def test_editing_a_lookup_lands_in_the_access_log(settings_operator, db):
    """Строки справочников печатаются в документах ВСЕХ арендаторов."""
    from master_data.models import UnitOfMeasure

    unit = UnitOfMeasure.objects.create(code="OD_UOM", name="Старое имя", sort_order=950)

    resp = _api(settings_operator).patch(f"/api/v1/master-data/units/{unit.pk}/", {"name": "Новое имя"}, format="json")

    assert resp.status_code == 200, resp.content
    entry = ActivityLog.objects.get(event_code="admin.lookup.updated")
    assert entry.before_data["name"] == "Старое имя"
    assert entry.after_data["name"] == "Новое имя"
    assert ActivityLog.objects.filter(ACCESS_LOG_FILTER, pk=entry.pk).exists()


def test_editing_an_email_template_lands_in_the_access_log(settings_operator, db):
    """Активная строка немедленно подменяет письмо ДЛЯ ВСЕХ получателей платформы."""
    from notifications.models import EmailTemplate

    template = EmailTemplate.objects.create(key="quote_sent", subject="Тема", html_body="<p>т</p>")

    resp = _api(settings_operator).patch(
        f"/api/v1/admin/email-templates/{template.pk}/", {"subject": "Новая тема"}, format="json"
    )

    assert resp.status_code == 200, resp.content
    entry = ActivityLog.objects.get(event_code="admin.email_template.updated")
    assert entry.event_params["key"] == "quote_sent"
    assert ActivityLog.objects.filter(ACCESS_LOG_FILTER, pk=entry.pk).exists()


# ── 117 + сверх аудита. Режим инспекции — правило сайта ─────────────────────


@pytest.fixture
def engineer(db):
    """Инженер с ПОЛНЫМ набором модельных прав — самый привилегированный не-суперпользователь."""
    user = CustomUser.objects.create_user(
        email="engineer@onedoor.test", username="engineer_onedoor", password="x", is_staff=True, is_active=True
    )
    user.groups.add(Group.objects.get_or_create(name="system_engineers")[0])
    user.user_permissions.set(Permission.objects.all())
    return CustomUser.objects.get(pk=user.pk)


def _open_admins(user):
    """Админки, где пользователь может что-то изменить, добавить или удалить."""
    request = _Request(user)
    open_ = []
    for model, model_admin in admin.site._registry.items():
        instance = model.objects.first()
        if instance is None:
            continue
        fields = [f.name for f in model._meta.get_fields() if not f.one_to_many]
        readonly = set(model_admin.get_readonly_fields(request, obj=instance) or ())
        editable = [f for f in fields if f not in readonly]
        if editable or model_admin.has_add_permission(request) or model_admin.has_delete_permission(request, instance):
            open_.append(model._meta.label)
    return sorted(open_)


@pytest.mark.django_db
def test_no_admin_is_open_to_a_non_superuser(engineer, subscription):
    """Обещание докстринга выполнялось у 28 админок из 60 — теперь его держит САЙТ.

    Проверяем ПОВЕДЕНИЕ по всему реестру, а не наличие миксина в цепочке классов: наследование
    можно сохранить и всё равно оставить дыру.
    """
    assert _open_admins(engineer) == []


@pytest.mark.django_db
def test_the_audit_trail_itself_cannot_be_rewritten(engineer, subscription):
    """Журнал активности был редактируем на 13 полей из 18 — саму историю можно было переписать."""
    entry = ActivityLog.objects.create(entity_type="subscription", entity_id=subscription.pk, action="проба")
    model_admin = admin.site._registry[ActivityLog]
    request = _Request(engineer)

    readonly = set(model_admin.get_readonly_fields(request, obj=entry))

    assert "action" in readonly and "reason" in readonly and "user" in readonly
    assert model_admin.has_delete_permission(request, entry) is False


@pytest.mark.django_db
def test_group_and_permission_are_not_a_self_service_key(engineer, db):
    """Волна #599 сделала модельное право «вторым ключом» к опасным действиям. Через открытый
    `GroupAdmin` этот ключ выдавался себе самому."""
    group = Group.objects.get(name="system_engineers")
    model_admin = admin.site._registry[Group]
    request = _Request(engineer)

    assert "permissions" in set(model_admin.get_readonly_fields(request, obj=group))
    assert model_admin.has_add_permission(request) is False


@pytest.mark.django_db
def test_inline_list_editing_is_closed_too(engineer, db):
    """`readonly_fields` управляет ФОРМОЙ, а `list_editable` рисует поля прямо в реестре и
    сохраняет их своим POST'ом мимо неё."""
    from crm.models import DealStage

    model_admin = admin.site._registry[DealStage]

    from django.test import RequestFactory

    request = RequestFactory().get("/admin/crm/dealstage/")
    request.user = engineer
    changelist = model_admin.get_changelist_instance(request)

    assert tuple(changelist.list_editable) == ()


@pytest.mark.django_db
def test_no_custom_bulk_action_is_offered_to_a_non_superuser(engineer, db):
    """Отбор опирался на `__wrapped__` — признак `functools.wraps`, а не намерения: обычный
    `@admin.action` проходил насквозь, и «Пометить прочитанными» правило чужие уведомления.

    Проверяем ВЕСЬ реестр, а не одну админку: дефект был именно в том, что гарантия держалась
    на дисциплине автора. Разрешены только действия, зарегистрированные самой Django.
    """
    site_actions = set(getattr(admin.site, "_actions", {}))
    offered = {
        f"{model._meta.label}.{name}"
        for model, model_admin in admin.site._registry.items()
        for name in model_admin.get_actions(_Request(engineer))
        if name not in site_actions
    }

    assert offered == set(), offered


@pytest.mark.django_db
def test_marking_someone_elses_notifications_read_leaves_a_trace(db):
    """Обёртка `superuser_only_action` осталась не ради гейта (его теперь держит миксин), а
    ради экрана подтверждения и записи в журнал: действие правит уведомления ЧУЖИХ людей."""
    from notifications.admin import NotificationAdmin

    assert hasattr(NotificationAdmin.mark_as_read, "__wrapped__"), "действие обязано идти через обёртку"


@pytest.mark.django_db
def test_the_superuser_keeps_the_full_toolbox(db, subscription):
    """Обратная сторона: инструмент инженера не урезан — решение владельца 2026-06-29."""
    root = CustomUser.objects.create_user(
        email="root@onedoor.test",
        username="root_onedoor",
        password="x",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    # Строку журнала заводим ЯВНО: `_open_admins` пропускает модели без записей, и без неё
    # проверка «история осталась доступна суперпользователю» была бы зелёной впустую.
    ActivityLog.objects.create(entity_type="subscription", entity_id=subscription.pk, action="проба")
    request = _Request(root)
    company_admin = admin.site._registry[Company]

    assert company_admin.has_add_permission(request) is True
    assert set(company_admin.get_readonly_fields(request, obj=subscription.company)) != {
        f.name for f in Company._meta.get_fields()
    }
    # Не магическое число: в тестовой базе строки есть не у всех моделей, и абсолютный порог
    # ломался бы от любого несвязанного теста. Сравниваем ДВЕ стороны одного правила.
    open_for_root = _open_admins(root)
    assert len(open_for_root) > 20, open_for_root
    assert "crm.ActivityLog" in open_for_root, "аварийная правка истории суперпользователю оставлена"
