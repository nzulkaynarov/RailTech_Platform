"""
Меню и дверь говорят одно и то же; мастер компаний не оставляет владельца без роли.

Находки 55, 56, 57 прогона 20-08 (замеры 25-08):

* **57.** В боковом меню Unfold 38 прямых ссылок и НИ ОДНОГО ключа `permission`. Дверь в
  админку открывает членство в `system_engineers`, а страницы моделей требуют модельных прав —
  и группа заводится миграцией БЕЗ единого права. Инженер видел полное меню, где почти каждый
  пункт вёл на голый 403. Зеркало того класса, что уже чинили в операторской плоскости: там
  пункт был спрятан, а дверь открыта.
* **55.** Мастер компаний выдавал владельцу `SystemRole` с кодом `CLIENT`, которого НЕТ:
  роли сведены к ADMIN/USER, CLIENT вычищен миграцией `accounts/0044`. `.first()` молча отдавал
  None, и владелец оставался без системной роли — в отличие от такого же владельца из
  регистрации.
* **56.** Дверь в мастер открывает `add_company`, а страница компании требует `view/change`.
  Актор ровно с правом «заводить» проходил мастер до конца и получал голый 403: компания
  создана, сообщения об успехе нет, вернуться некуда.
"""

import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from accounts.models import Company, CustomUser


@pytest.fixture
def engineer_without_permissions(db):
    """Каноничный член инженерной группы: миграция заводит её БЕЗ единого модельного права."""
    user = CustomUser.objects.create_user(
        email="bare@menu.test", username="bare_menu", password="Probe1234!", is_staff=True, is_active=True
    )
    group, _created = Group.objects.get_or_create(name="system_engineers")
    user.groups.add(group)
    return user


def _sidebar_items(user, rf):
    from django.contrib.admin import site

    request = rf.get("/admin/")
    request.user = user
    return [item for group in site.get_sidebar_list(request) for item in group["items"]]


# ── 57. Меню показывает только то, что откроется ────────────────────────────


def test_a_member_without_permissions_sees_no_dead_links(engineer_without_permissions, rf):
    items = _sidebar_items(engineer_without_permissions, rf)

    assert items, "заготовка обязана вернуть пункты — иначе тест зелёный по пустому обходу"
    assert [item["link"] for item in items if item["has_permission"]] == []


def test_a_granted_model_shows_up_and_the_rest_stays_hidden(engineer_without_permissions, rf):
    """Право на ОДНУ модель открывает ровно один пункт: меню повторяет права, а не заменяет их."""
    engineer_without_permissions.user_permissions.add(Permission.objects.get(codename="view_company"))
    user = CustomUser.objects.get(pk=engineer_without_permissions.pk)  # сброс кэша прав

    visible = [item["link"] for item in _sidebar_items(user, rf) if item["has_permission"]]

    assert visible == ["/admin/accounts/company/"]


def test_the_wizard_item_asks_for_the_right_to_create(engineer_without_permissions, rf):
    """Мастер — не просмотр: пункт закрыт тем же правом, которого требует сама страница."""
    engineer_without_permissions.user_permissions.add(Permission.objects.get(codename="add_company"))
    user = CustomUser.objects.get(pk=engineer_without_permissions.pk)

    visible = [item["link"] for item in _sidebar_items(user, rf) if item["has_permission"]]

    assert visible == ["/admin/accounts/company/wizard/"]


def test_the_superuser_still_sees_everything(db, rf):
    root = CustomUser.objects.create_user(
        email="root@menu.test",
        username="root_menu",
        password="x",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )

    items = _sidebar_items(root, rf)

    assert all(item["has_permission"] for item in items)
    # 36 после M1-ERP-02 волны 1b (ушли «Лиды с сайта» и «Сообщения»); 32 после волны 1c — ушли
    # «Заявки на роли», «KYC документы», «Статусы верификации», «Типы KYC-документов»; 31 после
    # волны 2 — ушли «Подписки поставщиков».
    assert len(items) >= 31, "инструмент инженера не урезан"


def test_every_menu_link_resolves_to_a_real_admin_page(db):
    """Ссылка, ведущая в никуда, — тот же дефект, только другой природы: право вывести из неё
    нельзя, и пункт остался бы видимым всегда."""
    from django.conf import settings
    from django.urls import Resolver404, resolve

    for group in settings.UNFOLD["SIDEBAR"]["navigation"]:
        for item in group.get("items", []):
            try:
                resolve(item["link"])
            except Resolver404:  # pragma: no cover — падение и есть сообщение
                pytest.fail(f"пункт меню ведёт в никуда: {item['link']}")
            assert callable(item.get("permission")), f"пункт без права: {item['link']}"


# ── 55/56. Мастер компаний ──────────────────────────────────────────────────


@pytest.fixture
def creator(db):
    """Актор ровно с правом «заводить компанию» — тем, что канонизирует гейт мастера."""
    user = CustomUser.objects.create_user(
        email="creator@wizard.test", username="creator_wizard", password="Probe1234!", is_staff=True, is_active=True
    )
    group, _created = Group.objects.get_or_create(name="system_engineers")
    user.groups.add(group)
    user.user_permissions.add(Permission.objects.get(codename="add_company"))
    return CustomUser.objects.get(pk=user.pk)


WIZARD_URL = "/admin/accounts/company/wizard/"
WIZARD_PREFIX = "company_wizard_view"


def _step(client, step, **fields):
    payload = {f"{WIZARD_PREFIX}-current_step": step}
    payload.update({f"{step}-{key}": value for key, value in fields.items()})
    return client.post(WIZARD_URL, payload)


def _run_wizard(client, inn="908300001", owner_email="owner@wizard.test"):
    from accounts.models import CompanyType

    _step(client, "requisites", name="Заведённая мастером", inn=inn)
    _step(client, "contacts", email="info@wizard.test")
    _step(client, "role", types=[CompanyType.objects.get(code="CLIENT").pk])
    return _step(client, "members", owner_email=owner_email, owner_first_name="Пётр")


def test_the_owner_gets_the_canonical_system_role(creator, client, db):
    """Роль `CLIENT` вычищена миграцией 0044 — мастер выдавал несуществующий код, `.first()`
    молча отдавал None, и владелец оставался без системной роли вовсе."""
    from accounts.constants import SystemRoleCode
    from accounts.models import SystemRole

    assert not SystemRole.objects.filter(code="CLIENT").exists(), "опорная точка: кода CLIENT нет"
    client.force_login(creator)

    _run_wizard(client)

    owner = CustomUser.objects.get(email="owner@wizard.test")
    assert owner.role is not None, "владелец без системной роли — не то же, что владелец из регистрации"
    assert owner.role.code == SystemRoleCode.USER


def test_the_company_is_really_created(creator, client, db):
    """Опорная точка: мастер работает — иначе тесты выше зелены по несозданной компании."""
    client.force_login(creator)

    _run_wizard(client, inn="908300002", owner_email="owner2@wizard.test")

    assert Company.objects.filter(inn="908300002").exists()


def test_the_creator_is_not_thrown_into_a_403(creator, client, db):
    """Мастер отрабатывал и выбрасывал актора на страницу, которую он открыть не может:
    компания создана, сообщения об успехе нет, вернуться некуда."""
    client.force_login(creator)

    response = _run_wizard(client, inn="908300003", owner_email="owner3@wizard.test")

    assert response.status_code == 302
    assert response.url == reverse("admin:index")
    assert client.get(response.url).status_code == 200, "адрес обязан открываться, а не давать 403"


def test_someone_who_can_open_the_company_lands_on_it(creator, client, db):
    """Обратная сторона: у кого право есть — тот попадает на карточку, как и раньше."""
    creator.user_permissions.add(Permission.objects.get(codename="view_company"))
    client.force_login(CustomUser.objects.get(pk=creator.pk))

    response = _run_wizard(client, inn="908300004", owner_email="owner4@wizard.test")

    company = Company.objects.get(inn="908300004")
    assert response.url == f"/admin/accounts/company/{company.pk}/change/"
