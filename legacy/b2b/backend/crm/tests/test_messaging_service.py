"""Service-level tests for crm.services.messaging.

Covers:
  * user_can_access_deal_chat — every grant path (superuser, platform admin,
    deal manager, deal client, routed seller, plain company member) and the
    deny paths (None / unauthenticated / unrelated user).
  * send_deal_message — admin-viewer / non-member / empty-text refusals, plus
    the happy path (message created, text stripped + truncated, audit row).
  * archive_messages_sync — empty / all-archived → zeros, pending → archived
    with metadata, already-archived skipped, storage failure appended to errors
    without marking that group's rows.

Storage is monkeypatched to an in-memory backend (CI has no MinIO — it uses
FileSystemStorage), and the channel layer is swapped for the in-memory backend
so the Message post_save broadcast never depends on Redis.
"""

import datetime

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.files.storage import InMemoryStorage

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm import services as crm_services
from crm.models import ActivityLog, Deal, DealSellerRouting, DealStage, Message
from crm.services.messaging import MAX_MESSAGE_LENGTH


@pytest.fixture(autouse=True)
def in_memory_channel_layer(settings):
    """Swap Redis channel layer for the in-memory backend so the Message
    post_save broadcast (crm.signals.broadcast_new_message) never hits Redis."""
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    from channels import layers

    layers.channel_layers.backends = {}
    yield
    layers.channel_layers.backends = {}


@pytest.fixture
def lookups(db):
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})


def _user(email, **extra):
    return CustomUser.objects.create_user(email=email, username=email, password="x", is_active=True, **extra)


def _member(company, email, *, can_sell=False, can_buy=False):
    user = _user(email)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


@pytest.fixture
def world(lookups):
    l2 = VerificationStatus.objects.get(code="L2_VERIFIED")
    buyer_co = Company.objects.create(name="Buyer Co", inn="B100", verification_status=l2)
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    member = _member(buyer_co, "member@t.test", can_buy=True)

    seller_co = Company.objects.create(name="Seller Co", inn="S100", verification_status=l2)
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller = _member(seller_co, "seller@t.test", can_sell=True)

    other_co = Company.objects.create(name="Unrelated Co", inn="U100", verification_status=l2)
    other_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    unrelated = _member(other_co, "unrelated@t.test", can_sell=True)

    manager = _user("manager@t.test")
    client = _user("client@t.test")
    superuser = _user("root@t.test", is_superuser=True, is_staff=True)
    admin_viewer = _user("admin@t.test", role=SystemRole.objects.get(code="ADMIN"))

    deal = Deal.objects.create(
        title="Chat deal",
        company=buyer_co,
        manager=manager,
        client=client,
        stage=DealStage.objects.get(code="DRAFT"),
    )
    return {
        "buyer_co": buyer_co,
        "member": member,
        "seller_co": seller_co,
        "seller": seller,
        "unrelated": unrelated,
        "manager": manager,
        "client": client,
        "superuser": superuser,
        "admin_viewer": admin_viewer,
        "deal": deal,
    }


# ── user_can_access_deal_chat ───────────────────────────────────────────────


@pytest.mark.django_db
def test_access_none_user_denied(world):
    assert crm_services.user_can_access_deal_chat(None, world["deal"]) is False


@pytest.mark.django_db
def test_access_unauthenticated_denied(world):
    assert crm_services.user_can_access_deal_chat(AnonymousUser(), world["deal"]) is False


@pytest.mark.django_db
def test_access_superuser_allowed(world):
    assert crm_services.user_can_access_deal_chat(world["superuser"], world["deal"]) is True


@pytest.mark.django_db
def test_access_platform_admin_allowed(world):
    # role ADMIN + no memberships → is_platform_admin property is True.
    assert crm_services.user_can_access_deal_chat(world["admin_viewer"], world["deal"]) is True


@pytest.mark.django_db
def test_access_deal_manager_allowed(world):
    assert crm_services.user_can_access_deal_chat(world["manager"], world["deal"]) is True


@pytest.mark.django_db
def test_access_deal_client_allowed(world):
    assert crm_services.user_can_access_deal_chat(world["client"], world["deal"]) is True


@pytest.mark.django_db
def test_access_routed_seller_allowed(world):
    DealSellerRouting.objects.create(deal=world["deal"], seller_company=world["seller_co"])
    assert crm_services.user_can_access_deal_chat(world["seller"], world["deal"]) is True


@pytest.mark.django_db
def test_access_plain_company_member_allowed(world):
    plain = _member(world["buyer_co"], "plain@t.test", can_buy=True)
    assert crm_services.user_can_access_deal_chat(plain, world["deal"]) is True


@pytest.mark.django_db
def test_access_unrelated_user_denied(world):
    # A seller member of an unrelated, un-routed company — not manager/client/member.
    assert crm_services.user_can_access_deal_chat(world["unrelated"], world["deal"]) is False


# ── send_deal_message ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_send_platform_admin_viewer_rejected(world):
    msg, err = crm_services.send_deal_message(world["admin_viewer"], world["deal"], "hi")
    assert msg is None
    assert err == "ADMIN_VIEWER_CANNOT_ACT"


@pytest.mark.django_db
def test_send_non_member_rejected(world):
    msg, err = crm_services.send_deal_message(world["unrelated"], world["deal"], "hi")
    assert msg is None
    assert err == "NOT_DEAL_MEMBER"


@pytest.mark.django_db
@pytest.mark.parametrize("text", ["", "   \n\t  "])
def test_send_empty_text_rejected(world, text):
    msg, err = crm_services.send_deal_message(world["member"], world["deal"], text)
    assert msg is None
    assert err == "EMPTY_MESSAGE"


@pytest.mark.django_db
def test_send_valid_message_created_and_stripped(world):
    msg, err = crm_services.send_deal_message(world["member"], world["deal"], "  hello there  ")
    assert err is None
    assert msg.pk is not None
    assert msg.sender_id == world["member"].id
    assert msg.deal_id == world["deal"].id
    assert msg.text == "hello there"


@pytest.mark.django_db
def test_send_truncates_to_max_length(world):
    long_text = "a" * (MAX_MESSAGE_LENGTH + 250)
    msg, err = crm_services.send_deal_message(world["member"], world["deal"], long_text)
    assert err is None
    assert len(msg.text) == MAX_MESSAGE_LENGTH


@pytest.mark.django_db
def test_send_writes_audit_entry(world):
    msg, err = crm_services.send_deal_message(world["member"], world["deal"], "audit me")
    assert err is None
    audit = ActivityLog.objects.filter(entity_type="deal", entity_id=world["deal"].id, user=world["member"])
    assert audit.count() == 1
    assert "audit me" in audit.first().detail


# ── archive_messages_sync ───────────────────────────────────────────────────


def _make_message(deal, sender, text, *, is_archived=False, on_date=None):
    message = Message.objects.create(deal=deal, sender=sender, text=text, is_archived=is_archived)
    if on_date is not None:
        stamped = datetime.datetime.combine(on_date, datetime.time(12, 0), tzinfo=datetime.timezone.utc)
        Message.objects.filter(pk=message.pk).update(timestamp=stamped)
    return message


@pytest.mark.django_db
def test_archive_empty_queryset_returns_zero(world):
    result = crm_services.archive_messages_sync(Message.objects.none())
    assert result == {"archived": 0, "files": 0, "errors": []}


@pytest.mark.django_db
def test_archive_all_already_archived_returns_zero(world, monkeypatch):
    monkeypatch.setattr("core.storage.get_private_storage", lambda: InMemoryStorage())
    _make_message(world["deal"], world["member"], "old", is_archived=True)
    result = crm_services.archive_messages_sync(Message.objects.filter(deal=world["deal"]))
    assert result == {"archived": 0, "files": 0, "errors": []}


@pytest.mark.django_db
def test_archive_pending_messages_marks_and_counts(world, monkeypatch):
    monkeypatch.setattr("core.storage.get_private_storage", lambda: InMemoryStorage())
    on_date = datetime.date(2026, 1, 15)
    first = _make_message(world["deal"], world["member"], "one", on_date=on_date)
    second = _make_message(world["deal"], world["member"], "two", on_date=on_date)

    result = crm_services.archive_messages_sync(Message.objects.filter(deal=world["deal"]))

    assert result["archived"] == 2
    assert result["files"] == 1  # same date → one JSONL file
    assert result["errors"] == []
    for message in (first, second):
        message.refresh_from_db()
        assert message.is_archived is True
        assert message.archived_at is not None
        assert message.archive_path.endswith("2026/01/15.jsonl")


@pytest.mark.django_db
def test_archive_skips_already_archived_rows(world, monkeypatch):
    monkeypatch.setattr("core.storage.get_private_storage", lambda: InMemoryStorage())
    pending = _make_message(world["deal"], world["member"], "fresh", on_date=datetime.date(2026, 2, 1))
    done = _make_message(world["deal"], world["member"], "already", is_archived=True, on_date=datetime.date(2026, 2, 1))

    result = crm_services.archive_messages_sync(Message.objects.filter(deal=world["deal"]))

    assert result["archived"] == 1  # only the pending row
    pending.refresh_from_db()
    done.refresh_from_db()
    assert pending.is_archived is True
    assert done.is_archived is True  # untouched (was already archived)


@pytest.mark.django_db
def test_archive_storage_failure_records_error_and_skips_group(world, monkeypatch):
    """A storage failure on one date's file appends to errors and leaves that
    group's rows un-archived, while other groups still archive."""
    from crm.tasks import _archive_path_for

    fail_date = datetime.date(2026, 3, 3)
    ok_date = datetime.date(2026, 4, 4)
    fail_path = _archive_path_for(fail_date)

    class FailingStorage(InMemoryStorage):
        def save(self, name, content, max_length=None):
            if name == fail_path:
                raise OSError("boom")
            return super().save(name, content, max_length=max_length)

    monkeypatch.setattr("core.storage.get_private_storage", lambda: FailingStorage())

    fail_msg = _make_message(world["deal"], world["member"], "will fail", on_date=fail_date)
    ok_msg = _make_message(world["deal"], world["member"], "will pass", on_date=ok_date)

    result = crm_services.archive_messages_sync(Message.objects.filter(deal=world["deal"]))

    assert result["archived"] == 1  # only the ok group
    assert result["files"] == 1  # 2 groups - 1 failed
    assert len(result["errors"]) == 1
    assert fail_path in result["errors"][0]

    fail_msg.refresh_from_db()
    ok_msg.refresh_from_db()
    assert fail_msg.is_archived is False  # failed group left untouched
    assert ok_msg.is_archived is True
