"""ARCH-01 — off-thread AI jobs: enqueue (202 + row-first AIJob ownership), status endpoint
IDOR guard + stable failure code, run_ai_job feature dispatch, and the draft-quote
gate-error → {"error": CODE} mapping.

Celery is never touched: `.apply_async` is stubbed, handlers are exercised by calling the
task directly with the underlying services monkeypatched at their source modules.
"""

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser
from sourcing.models import AIJob


@pytest.fixture
def stub_apply_async(monkeypatch):
    """Stub run_ai_job.apply_async (the enqueue path pre-generates the task id);
    records (args, task_id) calls."""
    calls = []

    def _apply_async(args=None, task_id=None, **kwargs):
        calls.append((args, task_id))
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("sourcing.tasks_ai.run_ai_job.apply_async", _apply_async)
    return calls


def _user(email):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)


# ── (a) enqueue: 202 + AIJob row owned by the caller (row FIRST, then publish) ──


@pytest.mark.django_db
def test_enqueue_creates_owned_aijob_and_returns_202(settings, stub_apply_async):
    settings.AI_IMPORT_ENABLED = True
    user = _user("aijob-owner@x.test")
    client = APIClient()
    client.force_authenticate(user)

    response = client.post("/api/v1/sourcing/match-catalog/", {"lines": [{"name": "Болт М12"}]}, format="json")

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    job = AIJob.objects.get(celery_task_id=task_id)
    assert job.owner_id == user.id
    assert job.feature == "match"
    # The clamped payload was published under the SAME pre-generated id the row holds.
    assert stub_apply_async == [
        (["match", {"lines": [{"name": "Болт М12"}], "domain_code": None, "top_k": 3}], task_id)
    ]


@pytest.mark.django_db
def test_enqueue_publish_failure_removes_row_and_returns_500(settings, monkeypatch):
    """Broker down → 500 AND no dangling ownership row (it would poll as eternally PENDING)."""
    from kombu.exceptions import OperationalError

    settings.AI_IMPORT_ENABLED = True
    user = _user("aijob-broker-down@x.test")

    def _boom(*args, **kwargs):
        raise OperationalError("broker unreachable")

    monkeypatch.setattr("sourcing.tasks_ai.run_ai_job.apply_async", _boom)
    client = APIClient()
    client.force_authenticate(user)
    response = client.post("/api/v1/sourcing/match-catalog/", {"lines": [{"name": "x"}]}, format="json")
    assert response.status_code == 500
    assert AIJob.objects.filter(owner=user).count() == 0


# ── (b) ai-status: 403 non-owner, 200 owner; FAILURE → stable code only ────────


class _FakeAsyncResult:
    def __init__(self, task_id):
        self.status = "SUCCESS"
        self.result = {"matches": []}

    def ready(self):
        return True

    def failed(self):
        return False


class _FakeFailedResult:
    def __init__(self, task_id):
        self.status = "FAILURE"
        # Internal detail that must NEVER reach the client (DB/SDK error text).
        self.result = Exception("column crm_quoteitem.secret does not exist; url=https://api.anthropic.com/x")

    def ready(self):
        return True

    def failed(self):
        return True


@pytest.mark.django_db
def test_ai_status_scoped_to_owner(monkeypatch):
    owner = _user("aijob-status-owner@x.test")
    stranger = _user("aijob-status-stranger@x.test")
    AIJob.objects.create(celery_task_id="aijob-task-0002", owner=owner, feature="match")
    monkeypatch.setattr("sourcing.ai_jobs.AsyncResult", _FakeAsyncResult)

    client = APIClient()
    client.force_authenticate(stranger)
    assert client.get("/api/v1/sourcing/ai-status/aijob-task-0002/").status_code == 403

    client.force_authenticate(owner)
    response = client.get("/api/v1/sourcing/ai-status/aijob-task-0002/")
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "aijob-task-0002"
    assert body["status"] == "SUCCESS"
    # The handler's dict is passed through verbatim (the old sync response shape).
    assert body["result"] == {"matches": []}


@pytest.mark.django_db
def test_ai_status_failure_returns_stable_code_not_exception_text(monkeypatch):
    """A crashed task must surface as the stable AI_JOB_FAILED code — never the raw
    exception text (DB error strings / SDK request ids would leak to the client)."""
    owner = _user("aijob-status-failed@x.test")
    AIJob.objects.create(celery_task_id="aijob-task-0003", owner=owner, feature="compose")
    monkeypatch.setattr("sourcing.ai_jobs.AsyncResult", _FakeFailedResult)

    client = APIClient()
    client.force_authenticate(owner)
    body = client.get("/api/v1/sourcing/ai-status/aijob-task-0003/").json()
    assert body["status"] == "FAILURE"
    assert body["result"] == {"status": "failed", "message": "AI_JOB_FAILED"}
    assert "crm_quoteitem" not in str(body)


# ── (c) run_ai_job dispatches each feature to its handler ─────────────────────


@pytest.mark.django_db
def test_dispatch_match(monkeypatch):
    from sourcing.tasks_ai import run_ai_job

    seen = {}

    def _fake_match(lines, domain_code=None, top_k=3):
        seen.update(lines=lines, domain_code=domain_code, top_k=top_k)
        return [{"line_index": 0, "candidates": []}]

    monkeypatch.setattr("sourcing.services_ai.match_lines_to_catalog", _fake_match)
    result = run_ai_job("match", {"lines": [{"name": "x"}], "domain_code": "RW", "top_k": 5})
    assert result == {"matches": [{"line_index": 0, "candidates": []}]}
    assert seen == {"lines": [{"name": "x"}], "domain_code": "RW", "top_k": 5}


@pytest.mark.django_db
def test_dispatch_preflight(monkeypatch):
    from sourcing.tasks_ai import run_ai_job

    monkeypatch.setattr(
        "sourcing.services_ai_preflight.pre_flight_check",
        lambda lines, domain_code=None: [{"line_index": 0, "issue": "vague"}],
    )
    result = run_ai_job("preflight", {"lines": [{"name": "x"}], "domain_code": None})
    assert result == {"findings": [{"line_index": 0, "issue": "vague"}]}


def _stage_extract_file(content: bytes) -> str:
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    return default_storage.save("ai_extract_tmp/test-extract.pdf", ContentFile(content))


@pytest.mark.django_db
def test_dispatch_extract(monkeypatch):
    """The document travels as a default_storage key (never base64 through the broker);
    the handler reads it, runs extract+reconcile, and ALWAYS deletes the temp file."""
    from django.core.files.storage import default_storage

    from sourcing.tasks_ai import run_ai_job

    seen = {}

    def _fake_extract(content, filename):
        seen.update(content=content, filename=filename)
        return {"total": "100.00", "currency_code": "UZS"}

    monkeypatch.setattr("sourcing.services_ai_extract.extract_document_fields", _fake_extract)
    monkeypatch.setattr(
        "sourcing.services_ai_extract.reconcile",
        lambda extracted, expected_total, expected_currency: {"ok": True, "mismatches": []},
    )
    file_key = _stage_extract_file(b"%PDF-1.4 stub")
    payload = {
        "file_key": file_key,
        "filename": "contract.pdf",
        "expected_total": "100.00",
        "expected_currency": "UZS",
        "kind": "quote",
        "reference_id": 7,
    }
    result = run_ai_job("extract", payload)
    assert result == {
        "reference": {"kind": "quote", "id": 7},
        "extracted": {"total": "100.00", "currency_code": "UZS"},
        "comparison": {"ok": True, "mismatches": []},
    }
    assert seen == {"content": b"%PDF-1.4 stub", "filename": "contract.pdf"}
    assert not default_storage.exists(file_key)  # temp file cleaned up


@pytest.mark.django_db
def test_dispatch_extract_failure_returns_error_code_and_cleans_up(monkeypatch):
    """A RuntimeError from the vision extraction becomes {"error": AI_EXTRACT_FAILED} —
    returned, not raised — and the staged temp file is still deleted."""
    from django.core.files.storage import default_storage

    from sourcing.tasks_ai import run_ai_job

    def _boom(content, filename):
        raise RuntimeError("AI_IMPORT_DISABLED")

    monkeypatch.setattr("sourcing.services_ai_extract.extract_document_fields", _boom)
    file_key = _stage_extract_file(b"x")
    payload = {"file_key": file_key, "filename": "doc.pdf"}
    assert run_ai_job("extract", payload) == {"error": "AI_EXTRACT_FAILED"}
    assert not default_storage.exists(file_key)


@pytest.mark.django_db
def test_dispatch_compose(monkeypatch):
    from sourcing.tasks_ai import run_ai_job

    monkeypatch.setattr(
        "sourcing.services_ai_conversational.build_request_from_text",
        lambda text, domain_code=None: {"items": [{"name": "Болт М12"}]},
    )
    assert run_ai_job("compose", {"text": "болты", "domain_code": None}) == {"items": [{"name": "Болт М12"}]}


@pytest.mark.django_db
def test_dispatch_enrich(monkeypatch):
    from sourcing.tasks_ai import run_ai_job

    monkeypatch.setattr(
        "catalog.ai_enrich.enrich_product",
        lambda name, domain_code=None, mpn=None, gost=None: {"description": "Колодка"},
    )
    result = run_ai_job("enrich", {"name": "Колодка", "domain_code": None, "mpn": None, "gost": None})
    assert result == {"suggestion": {"description": "Колодка"}}


@pytest.mark.django_db
def test_dispatch_chat_reply(monkeypatch):
    from sourcing.tasks_ai import run_ai_job

    user = _user("aijob-chat@x.test")
    seen = {}

    def _fake_reply(deal_id, requesting_user):
        seen.update(deal_id=deal_id, user_id=requesting_user.id)
        return {"draft": "Добрый день!"}

    monkeypatch.setattr("crm.services.suggest_chat_reply", _fake_reply)
    result = run_ai_job("chat_reply", {"deal_id": 42, "user_id": user.id})
    assert result == {"draft": "Добрый день!"}
    assert seen == {"deal_id": 42, "user_id": user.id}


def _make_diff_quote():
    from accounts.models import Company
    from crm.models import Deal, DealStage, Quote, QuoteStatus

    stage = DealStage.objects.get_or_create(code="SOURCING", defaults={"name": "Sourcing", "sort_order": 30})[0]
    status = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    company = Company.objects.create(name="Diff Job Co", inn="909909909")
    deal = Deal.objects.create(title="Diff", company=company, stage=stage)
    return Quote.objects.create(deal=deal, version=1, status=status)


@pytest.mark.django_db
def test_dispatch_quote_diff(monkeypatch):
    from sourcing.tasks_ai import run_ai_job

    quote = _make_diff_quote()
    user = _user("aijob-diff@x.test")
    seen = {}

    def _fake_diff(q):
        seen["quote_id"] = q.id
        return {"ai_enabled": False, "findings": []}

    # The worker re-runs the visibility gate (TOCTOU) with the recorded user.
    monkeypatch.setattr("crm.services.user_can_view_quote_diff", lambda u, q: True)
    monkeypatch.setattr("crm.services.quote_vs_request_diff", _fake_diff)
    result = run_ai_job("quote_diff", {"quote_id": quote.id, "user_id": user.id})
    assert result == {"ai_enabled": False, "findings": []}
    assert seen == {"quote_id": quote.id}


@pytest.mark.django_db
def test_dispatch_quote_diff_revoked_access_blocked(monkeypatch):
    """Visibility revoked between enqueue and execution → NOT_AUTHORIZED, no diff, no paid call."""
    from sourcing.tasks_ai import run_ai_job

    quote = _make_diff_quote()
    user = _user("aijob-diff-revoked@x.test")
    monkeypatch.setattr("crm.services.user_can_view_quote_diff", lambda u, q: False)
    monkeypatch.setattr(
        "crm.services.quote_vs_request_diff",
        lambda q: pytest.fail("diff must not run for a revoked user"),
    )
    result = run_ai_job("quote_diff", {"quote_id": quote.id, "user_id": user.id})
    assert result == {"error": "NOT_AUTHORIZED"}


# ── (d) unknown feature raises ValueError ─────────────────────────────────────


@pytest.mark.django_db
def test_unknown_feature_raises_value_error():
    from sourcing.tasks_ai import run_ai_job

    with pytest.raises(ValueError, match="Unknown AI job feature"):
        run_ai_job("bogus", {})


# ── (e) draft_quote handler maps gate errors into {"error": CODE} ─────────────


@pytest.mark.django_db
def test_draft_quote_gate_error_becomes_error_result(monkeypatch):
    from sourcing.tasks_ai import run_ai_job

    user = _user("aijob-draft@x.test")
    monkeypatch.setattr(
        "crm.services.draft_quote.generate_draft_quote",
        lambda deal_id, actor: (None, "AI_DRAFT_NOT_ENTITLED", 0),
    )
    result = run_ai_job("draft_quote", {"deal_id": 1, "user_id": user.id})
    assert result == {"error": "AI_DRAFT_NOT_ENTITLED"}
