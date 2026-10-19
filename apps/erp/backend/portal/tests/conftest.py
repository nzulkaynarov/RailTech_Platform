"""Test fixtures and helpers for Portal API tests."""

import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from parties.models import Company, CompanyType, Contact
from portal.models import PortalSession
from portal.services.tokens import hash_token
from rest_framework.test import APIClient

from core.tenant import own_company


def make_telegram_init_data(
    user_id: int, username: str = "", bot_token: str = "TEST_BOT_TOKEN_12345", auth_date: int = None
) -> str:
    """Generate a cryptographically valid Telegram WebApp initData string."""
    if auth_date is None:
        auth_date = int(time.time())

    user_obj = {
        "id": user_id,
        "first_name": "Test",
        "last_name": "User",
        "username": username,
        "language_code": "ru",
    }
    user_str = json.dumps(user_obj, separators=(",", ":"))

    params = [
        ("auth_date", str(auth_date)),
        ("query_id", "AAG_test_query_id"),
        ("user", user_str),
    ]
    check_items = sorted(params, key=lambda x: x[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in check_items)

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    hash_val = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    params.append(("hash", hash_val))
    return urllib.parse.urlencode(params)


def issue_test_acceptance_code(quote, email: str, code: str = "481516") -> str:
    """Активный одноразовый код акцепта КП — как его выпускает `issue_acceptance_code`, без письма."""
    from datetime import timedelta

    from django.utils import timezone
    from sales.models.acceptance import QuoteAcceptanceCode

    from crm.services.public_page import CODE_TTL_MINUTES, _hash_code

    QuoteAcceptanceCode.objects.create(
        quote=quote,
        email=email.strip().lower(),
        code_hash=_hash_code(code),
        expires_at=timezone.now() + timedelta(minutes=CODE_TTL_MINUTES),
    )
    return code


def make_portal_session(contact, company, auth_method: str) -> PortalSession:
    """Сессия портала; в базе только хеш токена, сырой — в `session.raw_token` (для cookie теста)."""
    raw_token = secrets.token_hex(32)
    session = PortalSession.objects.create(
        token_hash=hash_token(raw_token),
        contact=contact,
        company=company,
        auth_method=auth_method,
        expires_at=timezone.now() + timedelta(days=14),
    )
    session.raw_token = raw_token
    return session


@pytest.fixture
def bot_token(settings):
    token = "TEST_BOT_TOKEN_12345"
    settings.TELEGRAM_BOT_TOKEN = token
    return token


@pytest.fixture
def client_type():
    t, _ = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})
    return t


@pytest.fixture
def seller_company(db):
    company = own_company()
    if not company:
        supplier_type, _ = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик"})
        company = Company.objects.create(name="RailTech Head Company", inn="123456789")
        company.types.add(supplier_type)
    return company


@pytest.fixture
def client_company(db, client_type):
    comp = Company.objects.create(
        name="OOO Test Client Company",
        inn="987654321",
        bank_details="р/с 20208000123456789001 в АКИБ Ипотека Банк",
        language="ru",
    )
    comp.types.add(client_type)
    return comp


@pytest.fixture
def other_company(db, client_type):
    comp = Company.objects.create(
        name="OOO Other Client Company",
        inn="555666777",
        bank_details="р/с 20208000987654321002 в Капитал Банк",
        language="ru",
    )
    comp.types.add(client_type)
    return comp


@pytest.fixture
def client_contact(db, client_company):
    return Contact.objects.create(
        company=client_company,
        name="Azamat Client Contact",
        email="azamat.client@example.uz",
        phone="+998901234567",
        telegram_user_id=123456789,
        telegram_username="azamat_client",
        can_act=True,
        language="ru",
    )


@pytest.fixture
def readonly_contact(db, client_company):
    return Contact.objects.create(
        company=client_company,
        name="Sardor Readonly Contact",
        email="sardor.readonly@example.uz",
        phone="+998907654321",
        telegram_user_id=987654321,
        telegram_username="sardor_readonly",
        can_act=False,
        language="ru",
    )


@pytest.fixture
def other_contact(db, other_company):
    return Contact.objects.create(
        company=other_company,
        name="Bobur Other Contact",
        email="bobur.other@example.uz",
        phone="+998909998877",
        telegram_user_id=555444333,
        telegram_username="bobur_other",
        can_act=True,
        language="uz",
    )


@pytest.fixture
def client_session(db, client_contact, client_company):
    return make_portal_session(client_contact, client_company, "telegram")


@pytest.fixture
def readonly_session(db, readonly_contact, client_company):
    return make_portal_session(readonly_contact, client_company, "magic_link")


@pytest.fixture
def other_session(db, other_contact, other_company):
    return make_portal_session(other_contact, other_company, "telegram")


@pytest.fixture
def portal_client(client_session):
    client = APIClient()
    client.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = client_session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=client_session.raw_token)
    return client


@pytest.fixture
def readonly_portal_client(readonly_session):
    client = APIClient()
    client.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = readonly_session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=readonly_session.raw_token)
    return client


@pytest.fixture
def other_portal_client(other_session):
    client = APIClient()
    client.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = other_session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=other_session.raw_token)
    return client


@pytest.fixture
def anon_portal_client():
    return APIClient()
