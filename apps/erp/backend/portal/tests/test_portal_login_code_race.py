"""B-MAIL-1: гонка двух вводов одного кода (две вкладки, двойное нажатие) — реальные соединения Postgres.

Окно между «прочитал живые записи с кодом» и «погасил запись» растянуто паузой у первого участника: без блокировки строк
(`login_code._locked_candidates`, `select_for_update`) второй тоже видит запись живой и тоже получает сессию — один код
дал бы два входа. С блокировкой второй ждёт коммита первого, после него PostgreSQL перепроверяет условие (`used_at IS
NULL`) и запись уже не отдаёт — второй получает `LOGIN_CODE_INVALID`. Мутационная проверка — в описании PR
(ORCHESTRATOR §4.1): без `select_for_update` тест краснеет.
"""

from __future__ import annotations

import threading
import time

import pytest
from django.db import connection
from django.utils import timezone
from portal.exceptions import PortalValidationError
from portal.models import MagicLinkToken, PortalSession
from portal.services import login_code
from portal.services.tokens import hash_token

pytestmark = pytest.mark.django_db(transaction=True)

CODE = "407213"


def test_two_concurrent_entries_of_one_code_give_one_session(client_contact, monkeypatch):
    MagicLinkToken.objects.create(
        token_hash=hash_token("race-token-of-sufficient-length"),
        code_hash=login_code.hash_login_code(client_contact.pk, CODE),
        contact=client_contact,
        purpose=MagicLinkToken.PURPOSE_LOGIN,
        expires_at=timezone.now() + login_code.LOGIN_LINK_TTL,
    )

    original = login_code._locked_candidates
    first_read = threading.Event()

    def slow_candidates(contact):
        found = original(contact)
        if not first_read.is_set():
            first_read.set()
            time.sleep(1.5)  # первый держит строки: второй либо ждёт (блокировка), либо читает живую запись (гонка)
        return found

    monkeypatch.setattr(login_code, "_locked_candidates", slow_candidates)

    results: dict = {}

    def run(name):
        try:
            results[name] = login_code.exchange_login_code(client_contact.email, CODE)
        except PortalValidationError as exc:
            results[name] = exc
        finally:
            connection.close()

    first = threading.Thread(target=run, args=("first",))
    second = threading.Thread(target=run, args=("second",))
    first.start()
    assert first_read.wait(5)
    second.start()
    first.join(10)
    second.join(10)

    sessions = [r for r in results.values() if isinstance(r, tuple)]
    refused = [r for r in results.values() if isinstance(r, PortalValidationError)]
    assert len(sessions) == 1, results
    assert len(refused) == 1 and refused[0].detail == "LOGIN_CODE_INVALID"
    assert PortalSession.objects.filter(contact=client_contact).count() == 1
