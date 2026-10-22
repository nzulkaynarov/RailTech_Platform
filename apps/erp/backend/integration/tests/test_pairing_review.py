"""Правки ревью сопряжения (M3-ERP-05): аудит после коммита, гонка двух приёмов, закрытие окна bootstrap командой.

1. Сбой записи аудита после коммита сопряжения не превращает успех в 500 (окно закрыто, секреты уже заменены);
2. два одновременных приёма (по одному коду; два bootstrap) — выигрывает ровно один, секреты победителя целы;
3. `manage.py pairing_close_bootstrap` — идемпотентно закрывает окно (живые стенды, где шов настроен через `.env`).
"""

from __future__ import annotations

import io
import json
import logging
import threading
import uuid

import pytest
from django.core.management import call_command
from django.db import connection
from integration.models import PairingState
from integration.services import bootstrap, credentials, pairing
from rest_framework.test import APIClient

URL = "/api/integration/v1/pairing/accept"
SSO_SECRET = "test-sso-secret"  # conftest._seam_secrets


def secrets_of(tag: str) -> dict[str, str]:
    return {
        "crm_to_erp_token": f"{tag}-crm-to-erp-" + "a" * 40,
        "erp_to_crm_token": f"{tag}-erp-to-crm-" + "b" * 40,
        "webhook_secret": f"{tag}-webhook-secret-" + "c" * 40,
    }


def raw(body: dict) -> bytes:
    return json.dumps(body, separators=(",", ":")).encode()


def post_bootstrap(body: dict):
    data = raw(body)
    import time

    proof = bootstrap.sign(SSO_SECRET, data, int(time.time()), uuid.uuid4().hex)
    return APIClient().post(URL, data=data, content_type="application/json", HTTP_X_PAIRING_PROOF=proof)


def post_code(code: str, body: dict):
    return APIClient().post(URL, data=raw(body), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {code}")


# ── 1. Сбой аудита не ломает успешное сопряжение ─────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["bootstrap", "code"])
def test_audit_failure_after_commit_does_not_turn_pairing_into_500(monkeypatch, caplog, method):
    body = secrets_of("audit")

    def boom(**kwargs):
        raise RuntimeError("audit storage is down")

    monkeypatch.setattr("core.audit.log_admin_action", boom)
    with caplog.at_level(logging.WARNING):
        response = post_bootstrap(body) if method == "bootstrap" else post_code(pairing.issue_code().code, body)
    assert response.status_code == 200, response.content
    assert response.json()["paired"] is True
    # Сопряжение состоялось: секреты заменены, окно закрыто.
    assert credentials.stored_crm_token() == body["crm_to_erp_token"]
    assert not pairing.bootstrap_is_open()
    # Сбой виден оператору в журнале, но без секретов.
    warning = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert "audit" in warning.lower() and method in warning
    for secret in body.values():
        assert secret not in warning


# ── 2. Гонка: выигрывает один ────────────────────────────────────────────────────────────────────────


def run_in_threads(calls):
    """Запускает вызовы одновременно (барьер), возвращает ответы в порядке `calls`."""
    barrier = threading.Barrier(len(calls))
    results: list = [None] * len(calls)

    def worker(index, call):
        try:
            barrier.wait(timeout=10)
            results[index] = call()
        except BaseException as exc:  # noqa: BLE001 - тест сам проверит результат
            results[index] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i, call)) for i, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_accepts_with_one_code_only_one_wins():
    code = pairing.issue_code().code
    first, second = secrets_of("race-one"), secrets_of("race-two")
    results = run_in_threads([lambda: post_code(code, first), lambda: post_code(code, second)])
    assert not any(isinstance(r, BaseException) for r in results), results
    assert sorted(r.status_code for r in results) == [200, 401]
    loser = next(r for r in results if r.status_code == 401)
    assert loser.json() == {"detail": "PAIRING_CODE_USED"}
    winner_body = first if results[0].status_code == 200 else second
    assert credentials.stored_crm_token() == winner_body["crm_to_erp_token"]
    assert credentials.webhook_secret() == winner_body["webhook_secret"]


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_bootstraps_only_one_wins_and_the_window_closes():
    first, second = secrets_of("boot-one"), secrets_of("boot-two")
    results = run_in_threads([lambda: post_bootstrap(first), lambda: post_bootstrap(second)])
    assert not any(isinstance(r, BaseException) for r in results), results
    assert sorted(r.status_code for r in results) == [200, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json() == {"detail": "BOOTSTRAP_CLOSED"}
    winner_body = first if results[0].status_code == 200 else second
    assert credentials.stored_crm_token() == winner_body["crm_to_erp_token"]
    assert not pairing.bootstrap_is_open()


# ── 3. manage.py pairing_close_bootstrap ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_close_bootstrap_command_closes_the_window_and_is_idempotent():
    assert pairing.bootstrap_is_open()
    out = io.StringIO()
    call_command("pairing_close_bootstrap", stdout=out)
    assert not pairing.bootstrap_is_open()
    first_stamp = PairingState.objects.get(pk=1).bootstrap_used_at
    assert first_stamp is not None
    assert "закрыто" in out.getvalue().lower()
    again = io.StringIO()
    call_command("pairing_close_bootstrap", stdout=again)  # повтор — не ошибка и не сдвигает метку
    assert PairingState.objects.get(pk=1).bootstrap_used_at == first_stamp
    assert "уже" in again.getvalue().lower()


@pytest.mark.django_db
def test_after_close_command_bootstrap_is_409_but_the_code_path_still_works():
    call_command("pairing_close_bootstrap", stdout=io.StringIO())
    response = post_bootstrap(secrets_of("closed"))
    assert response.status_code == 409 and response.json() == {"detail": "BOOTSTRAP_CLOSED"}
    assert post_code(pairing.issue_code().code, secrets_of("by-code")).status_code == 200
