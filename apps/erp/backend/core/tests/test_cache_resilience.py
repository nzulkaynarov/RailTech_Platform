"""S0-2: отказ `redis-cache` не роняет ERP (ADR-0013 п. 5, ADR-0017).

Кэш Django (троттлинг, блокировка входа, справочники) при недоступном Redis отвечает «пусто» и пишет предупреждение, обычный
API-запрос остаётся 200, а троттлинг пропускает. Одноразовые метки (`jti` SSO, привязки и MCP, билет и код 2FA) идут через
`core.cache.fail_closed()`: при отказе — 503 с понятным текстом, токен не погашен и не принят повторно.
Недоступный Redis здесь — настоящий `ResilientRedisCache` на закрытом порту, а не мок.
"""

import ast
import logging
import time
import uuid
from pathlib import Path
from unittest import mock

import jwt
import pyotp
import pytest
from django.core.cache import cache
from integration.models import CrmUserMapping
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType
from accounts.services import two_factor
from core import cache as rt_cache
from core.cache import CacheUnavailable, fail_closed

pytestmark = pytest.mark.django_db

DEAD = {
    "default": {
        "BACKEND": "core.cache.ResilientRedisCache",
        "LOCATION": "redis://127.0.0.1:1/0",  # порт 1: соединение отклоняется сразу
        "TIMEOUT": 300,
        "OPTIONS": {"socket_connect_timeout": 1, "socket_timeout": 1},
    }
}
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
SSO_SECRET = "test-sso-secret-s0-2"
PASSWORD = "testpass123"


@pytest.fixture(autouse=True)
def _fresh_breaker():
    """Автомат отказа живёт в процессе: каждый тест начинает с закрытого."""
    rt_cache._state.update({"down_until": 0.0, "last_log": 0.0, "down": False})
    yield
    rt_cache._state.update({"down_until": 0.0, "last_log": 0.0, "down": False})


@pytest.fixture
def dead_cache(settings):
    settings.CACHES = DEAD
    return DEAD


def _sso_token(sub="8201"):
    now = int(time.time())
    payload = {
        "iss": "crm",
        "aud": "erp",
        "sub": sub,
        "email": "sso-staff@example.com",
        "name": "Сотрудник",
        "iat": now,
        "exp": now + 60,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, SSO_SECRET, algorithm="HS256")


def _staff_superuser(user_factory):
    return user_factory(email="staff@example.com", username="staff", is_superuser=True)


# ─── Поведение обёртки над RedisCache ───────────────────────────────────────────────────────────


def test_dead_redis_answers_empty_instead_of_raising(dead_cache):
    assert cache.get("k") is None
    assert cache.get("k", "fallback") == "fallback"
    assert cache.set("k", 1, 10) is None
    assert cache.add("k", 1, 10) is True  # «замок взят»: работа идёт без кэша
    assert cache.get_many(["a", "b"]) == {}
    assert cache.has_key("k") is False
    assert cache.delete("k") is False
    assert cache.incr("k") == 1
    assert cache.get_or_set("k", lambda: "computed", 10) == "computed"
    cache.delete_many(["a", "b"])
    cache.clear()


def test_outage_is_logged_as_a_warning_without_keys_and_not_flooded(dead_cache, caplog):
    with caplog.at_level(logging.WARNING, logger="core.cache"):
        for _ in range(5):
            cache.get("secret-key-name")
    warnings = [r for r in caplog.records if r.name == "core.cache"]
    assert len(warnings) == 1
    text = warnings[0].getMessage()
    assert "недоступен" in text and "ERP работает без кэша" in text
    assert "secret-key-name" not in text and "redis://" not in text


def test_breaker_skips_redis_after_a_failure(dead_cache):
    cache.get("a")
    with mock.patch("django.core.cache.backends.redis.RedisCache.get", side_effect=AssertionError("ходил в Redis")):
        assert cache.get("b") is None  # автомат открыт: Redis не опрашивается


def test_recovery_is_logged_and_the_breaker_closes(dead_cache, caplog):
    cache.get("a")  # отказ: автомат открыт, состояние «down»
    assert rt_cache._state["down"] is True
    rt_cache._state["down_until"] = 0.0  # окно автомата прошло
    with caplog.at_level(logging.WARNING, logger="core.cache"):
        with mock.patch("django.core.cache.backends.redis.RedisCache.get", return_value="v"):
            assert cache.get("a") == "v"
    assert rt_cache._state["down"] is False
    assert any("снова доступен" in r.getMessage() for r in caplog.records)


def test_fail_closed_raises_cache_unavailable_and_ignores_the_breaker(dead_cache):
    assert cache.get("warm-up") is None  # открыл автомат
    with fail_closed():
        with pytest.raises(CacheUnavailable) as caught:
            cache.add("jti", 1, 60)
    assert caught.value.status_code == 503
    assert caught.value.detail == "SERVICE_TEMPORARILY_UNAVAILABLE"
    assert cache.add("jti", 1, 60) is True  # за пределами блока снова «открыто»


def test_errors_unrelated_to_availability_are_not_swallowed(dead_cache):
    with mock.patch("django.core.cache.backends.redis.RedisCache.incr", side_effect=ValueError("Key 'x' not found")):
        with pytest.raises(ValueError):
            cache.incr("x")


# ─── Обычный запрос ─────────────────────────────────────────────────────────────────────────────


def test_ordinary_api_request_is_200_with_the_cache_down(dead_cache, user_factory):
    user = _staff_superuser(user_factory)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    for _ in range(3):  # DRF-троттлинг (anon/user) читает и пишет тот же кэш
        response = client.get("/api/v1/accounts/me/")
        assert response.status_code == 200, response.content


def test_throttling_lets_requests_through_while_the_cache_is_down(dead_cache, user_factory):
    _staff_superuser(user_factory)
    client = APIClient()
    creds = {"email": "nobody@example.com", "password": "wrong"}
    codes = {client.post("/api/v1/auth/token/", creds, format="json").status_code for _ in range(12)}
    assert codes == {401}  # с рабочим кэшем 11-я попытка с IP дала бы 429 (test_rate_limiting.py)


def test_health_stays_green_with_the_cache_down(dead_cache, client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_integration_health_does_not_depend_on_the_cache(dead_cache):
    from integration.services.system import get_system_health

    health, status_code = get_system_health()
    assert health["queue_alive"] is True  # очередь = брокер; кэш — отдельный экземпляр
    assert status_code == 200


# ─── Одноразовые метки: отказ безопаснее пропуска ──────────────────────────────────────────────


@pytest.fixture
def sso_user(settings, user_factory, workspace_role_factory):
    settings.PLATFORM_SSO_SECRET = [SSO_SECRET]
    settings.PLATFORM_SSO_ENABLED = True
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0]
    company = Company.objects.create(name="Своя компания", inn="500000082")
    company.types.add(supplier)
    settings.OWN_COMPANY_ID = company.pk
    user = user_factory(email="sso-staff@example.com", username="sso-staff")
    CompanyMember.objects.create(user=user, company=company, role=workspace_role_factory("MEMBER", "Member"))
    CrmUserMapping.objects.create(user=user, crm_user_id=8201)
    return user


def test_sso_exchange_is_refused_with_a_clear_error_while_the_cache_is_down(settings, sso_user):
    token = _sso_token()
    settings.CACHES = DEAD
    response = APIClient().post("/api/v1/auth/sso/exchange/", {"token": token}, format="json")
    assert response.status_code == 503
    body = response.json()
    assert body["detail"] == "SSO_TEMPORARILY_UNAVAILABLE"
    assert "Повторите попытку" in body["message"]
    assert settings.REFRESH_COOKIE_NAME not in response.cookies  # сессия не выдана

    settings.CACHES = LOCMEM  # кэш вернулся: тот же токен не погашен и работает ровно один раз
    cache.clear()
    first = APIClient().post("/api/v1/auth/sso/exchange/", {"token": token}, format="json")
    assert first.status_code == 200, first.content
    again = APIClient().post("/api/v1/auth/sso/exchange/", {"token": token}, format="json")
    assert again.status_code == 401 and again.json()["detail"] == "TOKEN_ALREADY_USED"


def test_two_factor_login_step_is_refused_with_a_clear_error_while_the_cache_is_down(settings, user_factory):
    user = _staff_superuser(user_factory)
    secret = pyotp.random_base32()
    user.totp_secret = two_factor.encrypt_totp_secret(secret)
    user.is_2fa_enabled = True
    user.save(update_fields=["totp_secret", "is_2fa_enabled"])
    ticket = two_factor.issue_login_ticket(user)
    code = pyotp.TOTP(secret).now()
    payload = {"temp_token": ticket, "code": code}

    settings.CACHES = DEAD
    refused = APIClient().post("/api/v1/auth/login/2fa/", payload, format="json")
    assert refused.status_code == 503
    assert refused.json()["detail"] == "2FA_TEMPORARILY_UNAVAILABLE"
    assert "Повторите попытку" in refused.json()["message"]
    assert settings.REFRESH_COOKIE_NAME not in refused.cookies

    settings.CACHES = LOCMEM  # билет и код не потрачены: после восстановления вход проходит один раз
    cache.clear()
    assert APIClient().post("/api/v1/auth/login/2fa/", payload, format="json").status_code == 200
    assert APIClient().post("/api/v1/auth/login/2fa/", payload, format="json").status_code == 400


def test_ws_ticket_is_not_issued_without_a_place_to_store_it(settings, user_factory):
    user = _staff_superuser(user_factory)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    settings.CACHES = DEAD
    response = client.post("/api/v1/auth/ws-ticket/")
    assert response.status_code == 503
    assert response.json() == {"detail": "SERVICE_TEMPORARILY_UNAVAILABLE"}


def test_mcp_jti_fails_closed(dead_cache):
    from integration.mcp.context import AgentContext, mark_used

    context = AgentContext(
        crm_client_id=1,
        erp_company_id=None,
        mode="prospect",
        language="ru",
        iat=0,
        exp=0,
        jti=str(uuid.uuid4()),
        trace_id=None,
    )
    with pytest.raises(CacheUnavailable):
        mark_used(context)


def test_pairing_bootstrap_is_refused_with_503_while_the_cache_is_down(settings):
    """Привязка ERP к CRM по доказательству: повтор не проверить — 503, окно привязки остаётся открытым."""
    import json

    from integration.models import PairingState
    from integration.services import bootstrap, pairing

    body = json.dumps(
        {"crm_to_erp_token": "c" * 40, "erp_to_crm_token": "e" * 40, "webhook_secret": "w" * 40}, separators=(",", ":")
    ).encode()
    proof = bootstrap.sign("test-sso-secret", body, int(time.time()), uuid.uuid4().hex)
    settings.CACHES = DEAD
    response = APIClient().post(
        "/api/integration/v1/pairing/accept", data=body, content_type="application/json", HTTP_X_PAIRING_PROOF=proof
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "SERVICE_TEMPORARILY_UNAVAILABLE"}
    assert pairing.bootstrap_is_open()
    assert not PairingState.objects.filter(bootstrap_used_at__isnull=False).exists()


def test_mcp_gate_answers_503_while_the_jti_store_is_down(settings):
    from integration.tests.mcp_support import MCP_SECRET, make_context_token, raw_rpc

    settings.ERP_MCP_CONTEXT_KEY = MCP_SECRET
    token = make_context_token(crm_client_id=15, erp_company_id=None, mode="prospect")
    settings.CACHES = DEAD
    response = raw_rpc(token, "tools/call", {"name": "list_client_deals", "arguments": {}})
    assert response.status_code == 503
    assert response.json() == {"detail": "SERVICE_TEMPORARILY_UNAVAILABLE"}


# ─── Билет WebSocket: гасится строго и один раз ──────────────────────────────────────────────────


def _redeem_ws_ticket(ticket):
    from asgiref.sync import async_to_sync

    from core.middleware import get_user_from_ticket

    return async_to_sync(get_user_from_ticket)(ticket)


def test_ws_ticket_is_single_use_and_losing_the_race_is_refused(settings, user_factory):
    user = _staff_superuser(user_factory)
    settings.CACHES = LOCMEM
    cache.set("ws_ticket:t1", user.id, 30)
    # Выборка пользователя идёт в потоке consumer'а и в тесте с пулом БД не мостится (см. test_ws_ticket.py): подменяем её.
    with mock.patch("accounts.models.CustomUser.objects") as users:
        users.get.return_value = user
        assert _redeem_ws_ticket("t1") is user
    assert cache.get("ws_ticket:t1") is None  # погашен
    assert not _redeem_ws_ticket("t1").is_authenticated

    cache.set("ws_ticket:t2", user.id, 30)  # второй подключившийся читает билет, но удалить его уже не успевает
    with mock.patch("django.core.cache.backends.locmem.LocMemCache.delete", return_value=False):
        assert not _redeem_ws_ticket("t2").is_authenticated


def test_ws_ticket_is_refused_while_the_cache_is_down(dead_cache):
    assert not _redeem_ws_ticket("any").is_authenticated


# ─── Секрет события (код акцепта) живёт в кэше: «кэш лёг» ≠ «код протух» (rt_bus, B3) ──────────


@pytest.fixture
def code_event_world():
    from integration.models import CrmContactMapping
    from integration.tests.world import add_quote, make_company, make_deal
    from parties.models import Contact

    from crm.constants import QuoteStatusCode

    company = make_company(crm_client_id=7001)
    contact = Contact.objects.filter(company=company).first()
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=58)
    quote = add_quote(make_deal(company), 1, QuoteStatusCode.SENT, "5000000")
    return quote, contact


def _publish_code(quote, contact):
    from datetime import timedelta

    from django.db import transaction
    from django.utils import timezone
    from integration.services.events import publish_quote_acceptance_code_requested

    with transaction.atomic():
        return publish_quote_acceptance_code_requested(quote, contact, "739104", timezone.now() + timedelta(minutes=15))


def test_code_event_is_not_published_without_a_place_for_its_secret(settings, code_event_world):
    """Кэш лёг при публикации: код негде хранить — `CacheUnavailable`, события (даже маской) в outbox нет."""
    from integration.tests import bus_support

    quote, contact = code_event_world
    settings.CACHES = DEAD
    with pytest.raises(CacheUnavailable):
        _publish_code(quote, contact)
    assert bus_support.published("quote.acceptance_code_requested") == []


def test_cache_outage_rolls_back_the_issue_of_the_code(settings, code_event_world):
    """Выпуск кода и событие — одна транзакция: кэш лёг — кода нет ни в базе, ни в outbox, письмо не уходит."""
    from django.core import mail
    from integration.tests import bus_support
    from portal.services.acceptance import request_acceptance_code
    from sales.models.acceptance import QuoteAcceptanceCode

    quote, contact = code_event_world
    contact.telegram_user_id = 424242
    contact.save(update_fields=["telegram_user_id"])
    settings.CACHES = DEAD
    with pytest.raises(CacheUnavailable):
        request_acceptance_code(quote, contact)
    assert not QuoteAcceptanceCode.objects.filter(quote=quote).exists()
    assert bus_support.published("quote.acceptance_code_requested") == [] and mail.outbox == []


@pytest.mark.django_db(transaction=True)
def test_delivery_while_the_cache_is_down_loses_the_secret_not_the_service(settings, code_event_world):
    """Фактическое поведение библиотеки rt_bus: кэш лёг ДО доставки — секрета не достать, доставка уходит в `dead`
    (`SECRET_EXPIRED`), запрос подписчику не идёт и значение кода нигде не пишется. Это не то, что делал журнал вебхуков
    (откладывал доставку до возвращения кэша, S0-2); замена — клиент запрашивает код заново (срок кода 15 минут). Пункт
    в PR B3: ждать кэш вместо `dead` может только сама библиотека (хвост B1)."""
    import httpx
    from integration.bus import get_bus
    from rt_bus.django.models import Delivery

    quote, contact = code_event_world
    working = settings.CACHES
    event = _publish_code(quote, contact)  # секрет — в рабочий кэш
    sent = []
    bus = get_bus()
    previous = bus._http
    bus._http = httpx.Client(transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200)))
    try:
        settings.CACHES = DEAD  # кэш лёг до доставки
        bus.pump()
    finally:
        bus._http = previous
        settings.CACHES = working
    assert sent == []
    delivery = Delivery.objects.get(event_id=event.id)
    assert delivery.status == "dead" and "SECRET_EXPIRED" in (delivery.last_error or "")
    assert "739104" not in (delivery.last_error or "")


@pytest.mark.django_db(transaction=True)
def test_expired_secret_makes_the_delivery_dead_without_a_request(settings, code_event_world):
    """Секрет протух (TTL кэша вышел): поведение библиотеки — доставка `dead` с `SECRET_EXPIRED`, запроса нет, код не в логах."""
    import httpx
    from integration.bus import get_bus
    from rt_bus.django.models import Delivery

    quote, contact = code_event_world
    event = _publish_code(quote, contact)
    cache.delete(f"rt_bus:secret:{event.id}")  # TTL вышел
    sent = []
    bus = get_bus()
    previous = bus._http
    bus._http = httpx.Client(transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200)))
    try:
        bus.pump()
    finally:
        bus._http = previous
    assert sent == []
    delivery = Delivery.objects.get(event_id=event.id)
    assert delivery.status == "dead" and "SECRET_EXPIRED" in (delivery.last_error or "")


# ─── У каждого ключа кэша есть срок ────────────────────────────────────────────────────────────


def test_default_cache_has_a_finite_timeout():
    from django.conf import settings

    assert settings.CACHES["default"]["TIMEOUT"] not in (None, 0)
    assert settings.CACHES["default"]["BACKEND"] == "core.cache.ResilientRedisCache"


def test_lookup_version_key_expires(settings):
    from django.core.cache.backends.locmem import LocMemCache

    from master_data import signals
    from master_data.models import Country

    settings.CACHES = LOCMEM
    with mock.patch.object(LocMemCache, "set", autospec=True, side_effect=LocMemCache.set) as spy:
        signals.bump_lookup_version(Country)
    (_, key, value, *rest), kwargs = spy.call_args
    assert key == signals.lookup_version_key(Country) and value == 2
    timeout = kwargs.get("timeout", rest[0] if rest else None)
    assert timeout == signals.LOOKUP_VERSION_TTL and timeout > 0


def test_no_cache_write_in_application_code_lacks_a_ttl():
    """Кэш — volatile-lru: вытесняются только ключи со сроком. Запись с `timeout=None`/`None` третьим аргументом — навсегда."""
    backend = Path(__file__).resolve().parents[2]
    offenders = []
    for path in backend.rglob("*.py"):
        parts = path.relative_to(backend).parts
        if "tests" in parts or "migrations" in parts or path.name.startswith("test_") or path.name == "conftest.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            receiver = node.func.value
            is_cache = (isinstance(receiver, ast.Name) and receiver.id == "cache") or (
                isinstance(receiver, ast.Attribute) and receiver.attr == "cache"
            )
            if not is_cache or node.func.attr not in {"set", "add", "touch"}:
                continue
            timeout = next((kw.value for kw in node.keywords if kw.arg == "timeout"), None)
            if timeout is None and len(node.args) > 2:
                timeout = node.args[2]
            if isinstance(timeout, ast.Constant) and timeout.value is None:
                offenders.append(f"{path.relative_to(backend)}:{node.lineno}")
    assert offenders == [], f"запись в кэш без срока жизни: {offenders}"
