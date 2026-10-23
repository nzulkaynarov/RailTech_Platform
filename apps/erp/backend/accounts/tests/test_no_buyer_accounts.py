"""FIX-13 — покупательских аккаунтов в ERP нет (ORCHESTRATOR §3.1, CONVENTIONS.md §2 п.1).

Сторож от возврата: покупательский код, его маркеры и пути, существовавшие только для клиента,
не должны появиться снова. Клиент — контакт контрагента с сессией портала, а не `User`.
"""

import importlib

import pytest
from django.urls import Resolver404, resolve

from accounts.models import CompanyMember

#: Пути, которые существовали только для покупателя (акцепт / отклонение КП «за клиента», подпись договора
#: и приёмка акта клиентом из internal, сборка и отправка заявки, ИИ-помощники заявки).
REMOVED_PATHS = [
    ("POST", "/api/v1/crm/deals/1/add-request-item/"),
    ("POST", "/api/v1/crm/deals/1/add-request-items/"),
    ("POST", "/api/v1/crm/deals/1/submit-request/"),
    ("PATCH", "/api/v1/crm/deals/1/update-request-meta/"),
    ("POST", "/api/v1/crm/quotes/1/approve/"),
    ("POST", "/api/v1/crm/quotes/1/reject/"),
    ("POST", "/api/v1/crm/contracts/1/sign-client/"),
    ("POST", "/api/v1/crm/acts/1/sign/"),
    ("POST", "/api/v1/crm/acts/1/reject/"),
    ("POST", "/api/v1/sourcing/compose-request/"),
    ("POST", "/api/v1/sourcing/preflight-check/"),
]


@pytest.mark.parametrize("method,path", REMOVED_PATHS, ids=[f"{m} {p}" for m, p in REMOVED_PATHS])
def test_buyer_only_endpoint_is_gone(method, path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_buyer_access_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("accounts.services.buyer_access")


def test_buyer_gate_markers_are_gone():
    from accounts import constants
    from core import permissions

    assert not hasattr(permissions, "BUYER_ONLY")
    assert not hasattr(permissions.RoleGatedViewMixin, "buyer_actions")
    assert not hasattr(constants, "BuyerPermission")


def test_company_member_has_no_can_buy_flag():
    assert "can_buy" not in {field.name for field in CompanyMember._meta.get_fields()}
    assert "can_sell" in {field.name for field in CompanyMember._meta.get_fields()}
