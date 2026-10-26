"""Миграция sales/0006 на данных (волна 12, EDS-03): шаги «Руководитель» удаляются, КП, ждавшее только их, — в черновик.

Настоящий прогон миграции: `MigrationExecutor` откатывает `sales` к 0005 (схема волны 12 уже есть, 0006 — только
данные, обратный ход пустой), данные пишутся историческими моделями 0005 (у них ещё есть участие `HEAD` в выборе),
затем миграция применяется заново. Всё — в транзакции теста: после теста база та же.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db

BEFORE = [("sales", "0005_eds_calc_tasks_director_decision")]
AFTER = [("sales", "0006_drop_head_approval_steps")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def test_0006_drops_head_steps_and_returns_quotes_waiting_only_for_them_to_draft():
    old = _migrate(BEFORE)
    Deal = old.get_model("sales", "Deal")
    Quote = old.get_model("sales", "Quote")
    QuoteStatus = old.get_model("sales", "QuoteStatus")
    Step = old.get_model("sales", "QuoteApprovalStep")
    pending = QuoteStatus.objects.get(code="PENDING_APPROVAL")
    deal = Deal.objects.create(title="Миграция 0006")

    only_head = Quote.objects.create(deal=deal, version=1, status=pending)
    Step.objects.create(quote=only_head, order=100, participation="HEAD", status="PENDING")
    visa_left = Quote.objects.create(deal=deal, version=2, status=pending)
    Step.objects.create(quote=visa_left, order=1, participation="APPROVER", status="PENDING")
    Step.objects.create(quote=visa_left, order=100, participation="HEAD", status="PENDING")
    decided = Quote.objects.create(deal=deal, version=3, status=QuoteStatus.objects.get(code="READY_TO_SEND"))
    Step.objects.create(quote=decided, order=100, participation="HEAD", status="APPROVED")

    new = _migrate(AFTER)

    Quote = new.get_model("sales", "Quote")
    Step = new.get_model("sales", "QuoteApprovalStep")
    assert not Step.objects.filter(participation="HEAD").exists()
    assert Quote.objects.get(pk=only_head.pk).status.code == "DRAFT"
    assert Quote.objects.get(pk=visa_left.pk).status.code == "PENDING_APPROVAL", "виза ещё ждёт — КП на согласовании"
    assert Quote.objects.get(pk=decided.pk).status.code == "READY_TO_SEND"
    assert Step.objects.filter(quote_id=visa_left.pk, participation="APPROVER").count() == 1
