"""FX-3: ответ на запрос ссылки входа не раскрывает, зарегистрирован ли адрес (решение владельца 2026-11-08).

Время здесь не меряется: проверяется, что путь запроса один и тот же — те же запросы к базе, та же постановка задачи,
письмо и поиск контакта вне запроса; код, тело и заголовки совпадают.
"""

import json
import logging
import socket
import threading
import time
from unittest import mock

import pytest
import redis
from celery import Task, current_app
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from kombu.exceptions import OperationalError
from parties.models import Company, CompanyType, Contact
from portal.models import MagicLinkToken
from portal.tests.conftest import LOCMEM_BACKEND

MAGIC_LINK_URL = "/api/portal/v1/auth/magic-link"
DOMAIN = "@example.com"
PUBLISH_TIME_LIMIT = 4  # секунды; граница «анонимный запрос не держит воркер», а не замер разницы между адресами
SILENT_BROKER_LIFETIME = PUBLISH_TIME_LIMIT * 2
PER_REQUEST_HEADERS = {"x-request-id"}  # у каждого ответа свой, от адреса не зависит
KIND_NAMES = ["unknown", "archived_contact", "supplier", "archived_company", "ambiguous"]


def _address(tag: str) -> str:
    """Адреса одной длины: `Content-Length` не должен отличаться из-за самого адреса."""
    return f"{tag:x<16}{DOMAIN}"


def _company(name: str, inn: str, type_code: str, **kwargs) -> Company:
    company = Company.objects.create(name=name, inn=inn, **kwargs)
    company.types.set([CompanyType.objects.get_or_create(code=type_code, defaults={"name": type_code})[0]])
    return company


@pytest.fixture(autouse=True)
def _locmem_mail(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    mail.outbox.clear()


@pytest.fixture
def known_address(client_contact):
    client_contact.email = _address("known")
    client_contact.save(update_fields=["email"])
    return client_contact.email


@pytest.fixture
def address_of_kind(client_company, other_company, client_contact):
    """Адрес каждого «незарегистрированного» случая; у всех — другой путь в базе, ответ один."""

    def make(kind: str) -> str:
        address = _address(kind[:8])
        if kind == "archived_contact":
            Contact.objects.create(company=client_company, name="Архивный", email=address, archived_at=timezone.now())
        elif kind == "supplier":
            supplier = _company("Поставщик", "300000001", "SUPPLIER")
            Contact.objects.create(company=supplier, name="Поставщик", email=address)
        elif kind == "archived_company":
            archived = _company("Архив", "300000002", "CLIENT", is_active=False)
            Contact.objects.create(company=archived, name="Из архива", email=address)
        elif kind == "ambiguous":
            Contact.objects.create(company=client_company, name="Один", email=address)
            Contact.objects.create(company=other_company, name="Другой", email=address)
        return address

    return make


@pytest.fixture
def published():
    """Перехват публикации в брокер на уровне Celery: что и сколько раз ставит запрос, задачи не выполняются."""
    with mock.patch.object(Task, "apply_async", autospec=True) as calls:
        yield calls


@pytest.fixture
def point_celery_at(monkeypatch):
    """Настоящая публикация без подмен: брокер и бэкенд результатов переводятся на заданный адрес, кэши Celery сбрасываются."""
    app = current_app._get_current_object()
    saved = {key: app.conf[key] for key in ("broker_url", "result_backend", "task_always_eager")}

    def drop_caches():
        app._pool = None
        app.amqp._producer_pool = None
        app._local.__dict__.pop("backend", None)

    def point(url: str) -> None:
        # Celery читает эти переменные окружения раньше своих настроек.
        monkeypatch.setenv("CELERY_BROKER_URL", url)
        monkeypatch.setenv("CELERY_RESULT_BACKEND", url)
        app.conf.update(broker_url=url, result_backend=url, task_always_eager=False)
        drop_caches()

    yield point
    app.conf.update(**saved)
    drop_caches()


@pytest.fixture
def closed_port_url():
    """Порт, на котором никто не слушает: соединение сразу отклоняется."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"redis://127.0.0.1:{port}/0"


@pytest.fixture
def silent_redis_url():
    """Порт принимает соединение и молчит: отказа соединения нет. Закрывается сам, чтобы тест без таймаутов не завис."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(32)
    closer = threading.Timer(SILENT_BROKER_LIFETIME, listener.close)
    closer.start()
    yield f"redis://127.0.0.1:{listener.getsockname()[1]}/0"
    closer.cancel()
    listener.close()


def post(client, address):
    return client.post(MAGIC_LINK_URL, {"email": address}, format="json")


def fingerprint(response, address):
    """Всё, что видит клиент, кроме самого адреса, который он прислал."""
    return (
        response.status_code,
        response.content.replace(address.encode(), b"<address>"),
        sorted((k, v) for k, v in response.headers.items() if k.lower() not in PER_REQUEST_HEADERS),
        sorted(response.cookies.keys()),
    )


def run(client, address):
    """Запрос с перехваченной очередью: отпечаток ответа и SQL, выполненный внутри запроса."""
    with CaptureQueriesContext(connection) as queries:
        response = post(client, address)
    return response, [query["sql"] for query in queries]


@pytest.mark.django_db
class TestUniformLoginLinkAnswer:
    @pytest.mark.parametrize("kind", KIND_NAMES)
    def test_answer_is_the_same_for_every_kind_of_address(
        self, published, known_address, address_of_kind, anon_portal_client, kind
    ):
        address = address_of_kind(kind)

        known, _ = run(anon_portal_client, known_address)
        other, _ = run(anon_portal_client, address)

        assert known.status_code == 200
        assert known.data == {"status": "ok", "sent": True, "email": known_address}
        assert fingerprint(other, address) == fingerprint(known, known_address)

    @pytest.mark.parametrize("kind", KIND_NAMES)
    def test_request_does_the_same_work_for_every_kind_of_address(
        self, published, known_address, address_of_kind, anon_portal_client, kind
    ):
        address = address_of_kind(kind)

        _, known_sql = run(anon_portal_client, known_address)
        known_calls = list(published.call_args_list)
        published.reset_mock()
        _, other_sql = run(anon_portal_client, address)

        assert len(known_sql) == len(other_sql)
        assert [c.args[0].name for c in known_calls] == [c.args[0].name for c in published.call_args_list]
        assert len(known_calls) == 1

    def test_contact_lookup_and_mail_are_outside_the_request(self, published, known_address, anon_portal_client):
        _, sql = run(anon_portal_client, known_address)

        assert not [statement for statement in sql if "parties_contact" in statement]
        assert mail.outbox == []
        assert not MagicLinkToken.objects.exists()

    def test_broker_outage_gives_the_same_answer(self, published, known_address, anon_portal_client):
        published.side_effect = OperationalError("redis down")
        address = _address("nobody")

        known, _ = run(anon_portal_client, known_address)
        unknown, _ = run(anon_portal_client, address)

        assert known.status_code == 200
        assert fingerprint(unknown, address) == fingerprint(known, known_address)

    def test_dead_broker_and_backend_give_the_same_answer_quickly(
        self, caplog, point_celery_at, closed_port_url, known_address, anon_portal_client
    ):
        """Настоящий путь Celery: порт брокера и бэкенда результатов закрыт, подмен нет."""
        caplog.set_level(logging.DEBUG)
        point_celery_at(closed_port_url)
        address = _address("nobody")

        started = time.monotonic()
        known = post(anon_portal_client, known_address)
        known_elapsed = time.monotonic() - started
        unknown = post(anon_portal_client, address)

        assert known.status_code == 200
        assert fingerprint(unknown, address) == fingerprint(known, known_address)
        assert known_elapsed < PUBLISH_TIME_LIMIT
        assert known_address not in caplog.text.lower() and address not in caplog.text.lower()
        assert any("was not queued" in record.getMessage() for record in caplog.records)

    def test_live_broker_receives_the_task(self, settings, point_celery_at, known_address, anon_portal_client):
        """Ограничения публикации не должны мешать письму: при живом Redis задача доходит до очереди."""
        point_celery_at(settings.CELERY_BROKER_URL)
        client = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        queue = current_app.conf.task_default_queue
        client.delete(queue)

        response = post(anon_portal_client, known_address)

        assert response.status_code == 200
        assert client.llen(queue) == 1
        headers = json.loads(client.lpop(queue))["headers"]
        assert headers["task"] == "portal.send_magic_link_to_address"
        assert known_address not in headers["argsrepr"]

    def test_silent_broker_does_not_hold_the_request(self, point_celery_at, silent_redis_url, anon_portal_client):
        """Соединение принято, ответа нет: без таймаутов сокета запрос висел бы, пока брокер молчит."""
        point_celery_at(silent_redis_url)

        started = time.monotonic()
        response = post(anon_portal_client, _address("nobody"))

        assert response.status_code == 200
        assert time.monotonic() - started < PUBLISH_TIME_LIMIT

    def test_address_limit_answers_the_same(self, settings, published, known_address, anon_portal_client):
        settings.PORTAL_MAGIC_LINK_MAX_PER_HOUR = 1
        address = _address("nobody")

        known = [post(anon_portal_client, known_address) for _ in range(2)]
        unknown = [post(anon_portal_client, address) for _ in range(2)]

        assert [r.status_code for r in known] == [r.status_code for r in unknown] == [200, 429]
        assert fingerprint(known[1], known_address) == fingerprint(unknown[1], address)

    @pytest.mark.parametrize("body", [{"email": "not-an-email"}, {"email": ""}, {}])
    def test_validation_error_does_not_depend_on_the_address(self, published, anon_portal_client, body):
        response = anon_portal_client.post(MAGIC_LINK_URL, body, format="json")

        assert response.status_code == 422
        assert response.data["detail"] == "VALIDATION_ERROR"
        published.assert_not_called()
