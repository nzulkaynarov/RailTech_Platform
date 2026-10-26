"""«Журнал интеграций» (W13-A2): подписчики издателя — кто кому доставляет, очередь, предохранитель (без базы)."""

from __future__ import annotations

from datetime import timedelta

from rt_bus import Subscriber, Subscriptions
from rt_bus.journal import build_subscribers, public_endpoint, serves

from .conftest import SUBSCRIPTIONS, T0

SUBS = Subscriptions.parse(SUBSCRIPTIONS)


def _sub(name: str) -> Subscriber:
    found = SUBS.get(name)
    assert found is not None
    return found


def test_publisher_serves_only_subscribers_of_its_domains_and_never_itself() -> None:
    erp_domains = {"erp"}
    assert [s.name for s in SUBS.subscribers if serves(s, "erp", erp_domains)] == ["crm", "audit", "off"]
    # erp подписан на свой тип (deal.won), но себе издатель не доставляет
    assert not serves(_sub("erp"), "erp", erp_domains)
    # crm публикует и домен identity (ADR-0015): подписчик сотрудников получает его события
    people = Subscriber("people", "http://p.test/bus/v1/events", ("uz.railtech.identity.user.*.v1",))
    assert serves(people, "crm", {"crm", "identity"})
    assert not serves(people, "erp", erp_domains)
    # маска с подстановкой в домене
    anyone = Subscriber("all", "http://a.test/bus/v1/events", ("uz.railtech.*.v1",))
    assert serves(anyone, "eds", {"eds"})


def test_endpoint_hides_credentials_in_url() -> None:
    assert public_endpoint("http://crm-api:8000/bus/v1/events") == "http://crm-api:8000/bus/v1/events"
    assert public_endpoint("https://user:secret@hook.test:8443/bus/v1/events") == "https://hook.test:8443/bus/v1/events"


def test_subscribers_merge_file_queue_and_breaker_state() -> None:
    now = T0
    deliveries = [
        {"subscriber": "crm", "status": "pending", "n": 3, "oldest": now - timedelta(minutes=10)},
        {"subscriber": "crm", "status": "in_flight", "n": 1, "oldest": now - timedelta(minutes=2)},
        {"subscriber": "crm", "status": "dead", "n": 2, "oldest": now - timedelta(days=3)},
        # подписчика убрали из файла, а доставки остались
        {"subscriber": "gone", "status": "dead", "n": 1, "oldest": now - timedelta(days=1)},
    ]
    states = [
        {
            "subscriber": "crm",
            "consecutive_failures": 5,
            "paused_until": now + timedelta(minutes=4),
            "last_failure_at": now - timedelta(seconds=30),
            "last_success_at": now - timedelta(hours=1),
            "last_error": "HTTP 503: down",
        },
        # пауза прошла — не показываем как действующую
        {
            "subscriber": "audit",
            "consecutive_failures": 0,
            "paused_until": now - timedelta(minutes=1),
            "last_failure_at": None,
            "last_success_at": now,
            "last_error": None,
        },
    ]
    env = {"RT_BUS_ENDPOINT_CRM": "http://crm-api:8000/bus/v1/events"}
    views = {v.name: v for v in build_subscribers(now, "erp", {"erp"}, SUBS, deliveries, states, env)}
    assert sorted(views) == ["audit", "crm", "gone", "off"]

    crm = views["crm"]
    assert (crm.configured, crm.enabled, crm.endpoint) == (True, True, "http://crm-api:8000/bus/v1/events")
    assert (crm.pending, crm.in_flight, crm.dead) == (3, 1, 2)
    assert crm.oldest_undelivered_age_seconds == 600.0  # dead в возраст недоставленного не входит
    assert (crm.consecutive_failures, crm.paused_until) == (5, now + timedelta(minutes=4))
    assert crm.last_error == "HTTP 503: down"

    assert views["audit"].paused_until is None
    assert (views["audit"].pending, views["audit"].oldest_undelivered_age_seconds) == (0, None)
    assert (views["off"].enabled, views["off"].drop) == (False, True)
    gone = views["gone"]
    assert (gone.configured, gone.endpoint, gone.dead) == (False, None, 1)
