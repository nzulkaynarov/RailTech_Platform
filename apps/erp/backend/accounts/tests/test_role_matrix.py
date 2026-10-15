"""Матрица прав бэк-офиса на КАЖДОМ эндпоинте мутации (DoD M1-ERP-05).

Эндпоинты перечисляются из URLConf тем же перечислителем, что строит OpenAPI (drf-spectacular),
поэтому новый эндпоинт мутации без объявленного права роняет тест (а) — даже если о нём забыли
здесь. Для каждого объявленного эндпоинта (б):

* сотрудник без нужного права → 403 `ROLE_NOT_PERMITTED` (гейт срабатывает до поиска объекта,
  поэтому подставные id в пути годятся);
* сотрудник с этим правом и администратор (`is_superuser`) этого отказа не получают;
* `ADMIN_ONLY` — даже сотрудник со всеми правами получает 403 `PLATFORM_ADMIN_REQUIRED`;
* `BUYER_ONLY` — шаг покупателя: сотрудник со всеми правами получает 403 `ROLE_NOT_PERMITTED`;
* покупательский аккаунт (участник компании-клиента) на мутации бэк-офиса вне `buyer_actions`
  получает 403 `ROLE_NOT_PERMITTED`.
"""

import re

import pytest
from drf_spectacular.generators import EndpointEnumerator
from rest_framework.test import APIClient

from accounts.constants import ALL_PERMISSIONS
from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from core.permissions import ADMIN_ONLY, BUYER_ONLY, GATE_MARKERS, SELF_SERVICE, RoleGatedViewMixin

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Мутации БЕЗ права роли — короткий явный список с причиной. Новый пункт сюда — только с причиной,
# почему действие не принадлежит ни одной роли бэк-офиса.
OPEN_ENDPOINTS = {
    ("/api/v1/auth/token/", "POST"): "вход по паролю — до аутентификации",
    ("/api/v1/auth/token/refresh/", "POST"): "продление сессии по refresh-cookie",
    ("/api/v1/auth/login/2fa/", "POST"): "второй шаг входа (код 2FA)",
    ("/api/v1/auth/logout/", "POST"): "выход из своей сессии",
    ("/api/v1/auth/forgot-password/", "POST"): "сброс пароля — до аутентификации",
    ("/api/v1/auth/reset-password/", "POST"): "сброс пароля по токену из письма",
    ("/api/v1/auth/setup-password/", "POST"): "установка пароля по приглашению",
    ("/api/v1/auth/2fa/setup/", "POST"): "своя 2FA",
    ("/api/v1/auth/2fa/verify/", "POST"): "своя 2FA",
    ("/api/v1/auth/2fa/disable/", "POST"): "своя 2FA",
    ("/api/v1/auth/sessions/revoke-all/", "POST"): "завершить свои другие сессии",
    ("/api/v1/auth/ws-ticket/", "POST"): "билет своего WebSocket уведомлений",
    ("/api/v1/notifications/{pk}/mark_read/", "PATCH"): "отметить своё уведомление прочитанным",
    ("/api/v1/notifications/mark_all_read/", "PATCH"): "отметить свои уведомления прочитанными",
    ("/api/v1/public/quotes/{token}/accept/", "POST"): "публичная страница КП по токену (клиент, без входа)",
    ("/api/v1/public/quotes/{token}/reject/", "POST"): "публичная страница КП по токену (клиент, без входа)",
    ("/api/v1/public/quotes/{token}/request-code/", "POST"): "публичная страница КП по токену (клиент, без входа)",
    ("/api/v1/public/quotes/{token}/viewed/", "POST"): "публичная страница КП по токену (клиент, без входа)",
}


def _mutation_endpoints():
    rows = []
    for path, _regex, method, callback in EndpointEnumerator().get_api_endpoints():
        if method not in MUTATION_METHODS:
            continue
        # Клиентский портал (M2-ERP-01) изолирован от бэк-офиса и тестируется в portal/tests/
        if path.startswith("/api/portal/"):
            continue
        actions = getattr(callback, "actions", None) or {}
        rows.append((path, method, callback.cls, actions.get(method.lower()) or method))
    return sorted(rows, key=lambda row: (row[0], row[1]))


ENDPOINTS = _mutation_endpoints()
GATED = [row for row in ENDPOINTS if (row[0], row[1]) not in OPEN_ENDPOINTS]


def _id(row):
    return f"{row[1]} {row[0]}"


def _rule(row):
    _path, _method, view_cls, key = row
    return view_cls.required_permissions.get(key)


def _codes(rule):
    return list(rule) if isinstance(rule, tuple) else [rule]


def test_endpoint_inventory_is_not_empty():
    assert len(ENDPOINTS) > 150
    assert {(p, m) for p, m, _c, _k in ENDPOINTS} >= set(OPEN_ENDPOINTS), "устаревшая строка OPEN_ENDPOINTS"


@pytest.mark.parametrize("row", ENDPOINTS, ids=_id)
def test_every_mutation_declares_a_permission_or_a_reason(row):
    path, method, view_cls, key = row
    if (path, method) in OPEN_ENDPOINTS:
        assert OPEN_ENDPOINTS[(path, method)].strip()
        return
    assert issubclass(view_cls, RoleGatedViewMixin), f"{view_cls.__name__}: нет RoleGatedViewMixin"
    rule = view_cls.required_permissions.get(key)
    assert rule is not None, f"{view_cls.__name__}.required_permissions не объявляет {key!r}"
    if rule not in GATE_MARKERS:
        unknown = [code for code in _codes(rule) if code not in ALL_PERMISSIONS]
        assert not unknown, f"{view_cls.__name__}.{key}: коды вне каталога {unknown}"
    for action in view_cls.buyer_actions:
        assert action in view_cls.required_permissions, f"{view_cls.__name__}: buyer_action {action!r} без права"


# ── живая матрица ─────────────────────────────────────────────────────────────


@pytest.fixture
def world(db):
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0]
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client"})[0]
    own = Company.objects.create(name="Своя компания", inn="300000001")
    own.types.add(supplier)
    client = Company.objects.create(name="Клиент", inn="300000002")
    client.types.add(client_type)
    ws = WorkspaceRole.objects.get(code="MEMBER")
    owner_ws = WorkspaceRole.objects.get(code="OWNER")

    def member(company, email, permissions=None, workspace=ws):
        user = CustomUser.objects.create_user(email=email, username=email, password=None, is_active=True)
        membership = CompanyMember.objects.create(user=user, company=company, role=workspace, is_primary=True)
        if permissions is not None:
            role = CompanyRole.objects.create(company=company, name=f"r-{email}", permissions=list(permissions))
            membership.company_roles.add(role)
        return user

    superuser = CustomUser.objects.create_superuser(email="root@erp.example", username="root", password=None)
    return {
        "own": own,
        "client": client,
        "member": member,
        "superuser": superuser,
        "buyer": member(client, "buyer@client.example", workspace=owner_ws),
    }


def _call(user, path, method):
    client = APIClient()
    client.raise_request_exception = False
    client.force_authenticate(user)
    url = re.sub(r"\{[^}]+\}", "999999", path)
    return getattr(client, method.lower())(url, {}, format="json")


def _detail(response):
    data = getattr(response, "data", None)
    return data.get("detail") if isinstance(data, dict) else None


def _denied(response, code="ROLE_NOT_PERMITTED"):
    return response.status_code == 403 and _detail(response) == code


@pytest.mark.parametrize("row", GATED, ids=_id)
def test_role_matrix(world, row):
    path, method, view_cls, key = row
    rule = _rule(row)
    member = world["member"]
    admin_response = _call(world["superuser"], path, method)
    assert not _denied(admin_response) and not _denied(admin_response, "PLATFORM_ADMIN_REQUIRED")

    if rule == SELF_SERVICE:
        assert not _denied(_call(member(world["own"], "self@own.example", []), path, method))
        return
    if rule == ADMIN_ONLY:
        everything = member(world["own"], "all@own.example", ALL_PERMISSIONS)
        assert _denied(_call(everything, path, method), "PLATFORM_ADMIN_REQUIRED")
        return
    if rule == BUYER_ONLY:
        everything = member(world["own"], "all@own.example", ALL_PERMISSIONS)
        assert _denied(_call(everything, path, method))
        assert key in view_cls.buyer_actions
        assert not _denied(_call(world["buyer"], path, method))
        return

    codes = _codes(rule)
    without = member(world["own"], "without@own.example", [c for c in ALL_PERMISSIONS if c not in codes])
    assert _denied(_call(without, path, method)), f"без {codes} должен быть 403 ROLE_NOT_PERMITTED"
    holder = member(world["own"], "holder@own.example", [codes[0]])
    assert not _denied(_call(holder, path, method)), f"с {codes[0]} отказа по роли быть не должно"
    buyer_response = _call(world["buyer"], path, method)
    if key in view_cls.buyer_actions:
        assert not _denied(buyer_response)
    else:
        assert _denied(buyer_response), "покупательский аккаунт на мутации бэк-офиса"


@pytest.mark.parametrize("row", GATED, ids=_id)
def test_anonymous_gets_401_not_a_role_error(db, row):
    path, method, _view_cls, _key = row
    client = APIClient()
    client.raise_request_exception = False
    response = getattr(client, method.lower())(re.sub(r"\{[^}]+\}", "999999", path), {}, format="json")
    assert response.status_code in (401, 403)
    assert _detail(response) != "ROLE_NOT_PERMITTED"
