"""B-FX3-1: `POST /auth/code` проходит один и тот же путь работы для известного и неизвестного адреса.

Время не меряется: сравнивается последовательность запросов к базе (форма SQL без значений) для адреса без контакта,
архивного контакта, контакта-поставщика, неоднозначного адреса и известного контакта без живого кода. Раньше поиск
контакта и `_redeem` с `select_for_update` работали только у известного контакта.
"""

import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from parties.models import Company, CompanyType, Contact
from portal.exceptions import PortalValidationError
from portal.services.login_code import exchange_login_code

pytestmark = pytest.mark.django_db


def _company(name, inn, type_code, **kwargs):
    company = Company.objects.create(name=name, inn=inn, **kwargs)
    company.types.set([CompanyType.objects.get_or_create(code=type_code, defaults={"name": type_code})[0]])
    return company


def _shape(queries):
    shapes = []
    for query in queries:
        sql = re.sub(r'"s\d+_x\d+"', "?", query["sql"])
        sql = re.sub(r"'[^']*'|\b\d+\b", "?", sql)
        sql = re.sub(r"\(\?(, \?)+\)", "(?)", sql)
        shapes.append(sql)
    return shapes


def _work(email):
    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(PortalValidationError):
            exchange_login_code(email, "000000")
    return _shape(captured.captured_queries)


def _scene():
    client = _company("Client Co", "100100100", "CLIENT")
    Contact.objects.create(company=client, name="Known", email="known@example.com")
    archived = Contact.objects.create(company=client, name="Gone", email="gone@example.com", archived_at=timezone.now())
    supplier = _company("Supplier Co", "200200200", "SUPPLIER")
    Contact.objects.create(company=supplier, name="Supplier", email="supplier@example.com")
    other = _company("Other Co", "300300300", "CLIENT")
    for company in (client, other):
        Contact.objects.create(company=company, name="Shared", email="shared@example.com")
    return archived


@pytest.mark.parametrize(
    "email", ["nobody@example.com", "gone@example.com", "supplier@example.com", "shared@example.com"]
)
def test_unregistered_address_does_the_same_work_as_a_known_one(email):
    _scene()
    reference = _work("known@example.com")
    assert _work(email) == reference
