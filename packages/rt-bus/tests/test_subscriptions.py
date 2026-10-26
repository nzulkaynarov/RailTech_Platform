"""Подписки L5: маски, только свои, не себе, выключенный подписчик, перечитывание без перезапуска."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from rt_bus import Subscriptions, SubscriptionsError, SubscriptionsSource

from .conftest import FIXTURES, SUBSCRIPTIONS


@pytest.fixture
def subs() -> Subscriptions:
    return Subscriptions.parse(SUBSCRIPTIONS)


def names(items: list) -> list[str]:  # type: ignore[type-arg]
    return [s.name for s in items]


def test_masks_and_rules(subs: Subscriptions) -> None:
    assert names(subs.targets("uz.railtech.erp.quote.sent.v1", "rt://erp", "erp")) == ["crm", "audit"]
    assert names(subs.targets("uz.railtech.erp.invoice.paid.v1", "rt://erp", "erp")) == ["crm"]
    # версия входит в маску
    assert names(subs.targets("uz.railtech.erp.quote.sent.v2", "rt://erp", "erp")) == []
    # не себе: erp подписан на deal.won, но издатель — erp
    assert names(subs.targets("uz.railtech.erp.deal.won.v1", "rt://erp", "erp")) == ["crm"]
    # только свои: строка outbox ERP с чужим source никуда не уходит
    assert names(subs.targets("uz.railtech.crm.client.updated.v1", "rt://crm", "erp")) == []
    assert names(subs.targets("uz.railtech.crm.client.updated.v1", "rt://crm", "crm")) == ["erp"]
    assert names(subs.targets("uz.railtech.crm.contact.deleted.v1", "rt://crm", "crm")) == ["erp"]
    assert names(subs.targets("uz.railtech.crm.client.created.v1", "rt://crm", "crm")) == []


def test_disabled_subscriber_with_drop_gets_nothing(subs: Subscriptions) -> None:
    off = subs.get("off")
    assert off is not None
    assert (off.enabled, off.drop, off.dropping) == (False, True, True)
    assert off.matches("uz.railtech.erp.quote.sent.v1")
    assert "off" not in names(subs.targets("uz.railtech.erp.quote.sent.v1", "rt://erp", "erp"))


def test_disabled_subscriber_without_drop_still_gets_deliveries(subs: Subscriptions) -> None:
    """W11B-G-2: `enabled: false` не теряет события — строки доставки создаются, ретранслятор их не отправляет."""
    raw = yaml.safe_load(yaml.safe_dump(SUBSCRIPTIONS))
    for item in raw["subscribers"]:
        if item["name"] == "off":
            del item["drop"]
    held = Subscriptions.parse(raw)
    off = held.get("off")
    assert off is not None
    assert (off.enabled, off.drop, off.dropping) == (False, False, False)
    assert names(held.targets("uz.railtech.erp.quote.sent.v1", "rt://erp", "erp")) == ["crm", "audit", "off"]


def test_drop_matters_only_while_disabled() -> None:
    raw = yaml.safe_load(yaml.safe_dump(SUBSCRIPTIONS))
    raw["subscribers"][0]["drop"] = True  # crm включён: drop не действует
    crm = Subscriptions.parse(raw).get("crm")
    assert crm is not None
    assert (crm.enabled, crm.drop, crm.dropping) == (True, True, False)
    assert "crm" in names(Subscriptions.parse(raw).targets("uz.railtech.erp.quote.sent.v1", "rt://erp", "erp"))


def test_endpoint_env_override(subs: Subscriptions) -> None:
    crm = subs.get("crm")
    assert crm is not None
    assert crm.url({}) == "http://crm.test/bus/v1/events"
    assert crm.url({"RT_BUS_ENDPOINT_CRM": "http://crm-api:8000/bus/v1/events"}) == "http://crm-api:8000/bus/v1/events"
    assert crm.url({"RT_BUS_ENDPOINT_CRM": " "}) == "http://crm.test/bus/v1/events"


def test_contract_file_parses() -> None:
    subs = Subscriptions.load(FIXTURES / "bus" / "subscriptions.yaml")
    assert {s.name for s in subs.subscribers} >= {"crm", "erp"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(version=2),
        lambda d: d["subscribers"].append(dict(d["subscribers"][0])),  # имя не уникально
        lambda d: d["subscribers"][0].update(endpoint="http://crm/events"),
        lambda d: d["subscribers"][0].update(types=[]),
        lambda d: d["subscribers"][0].update(types=["erp.*"]),
        lambda d: d["subscribers"][0].update(enabled="yes"),
        lambda d: d["subscribers"][0].update(drop="yes"),
        lambda d: d["subscribers"][0].update(secret="x"),
    ],
)
def test_invalid_files_rejected(mutate) -> None:  # type: ignore[no-untyped-def]
    raw = yaml.safe_load(yaml.safe_dump(SUBSCRIPTIONS))
    mutate(raw)
    with pytest.raises(SubscriptionsError):
        Subscriptions.parse(raw)


def test_reload_on_change_without_restart(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.yaml"
    path.write_text(yaml.safe_dump(SUBSCRIPTIONS), encoding="utf-8")
    source = SubscriptionsSource(path)
    first = source.current()
    assert source.current() is first  # без изменений файл не перечитывается
    raw = yaml.safe_load(yaml.safe_dump(SUBSCRIPTIONS))
    raw["subscribers"].append(
        {"name": "late", "endpoint": "http://late.test/bus/v1/events", "types": ["uz.railtech.erp.*.v1"]}
    )
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert "late" in names(list(source.current().subscribers))
    # испорченный файл: остаются прежние подписки
    path.write_text("version: [", encoding="utf-8")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000))
    assert "late" in names(list(source.current().subscribers))


def test_missing_file_on_first_load(tmp_path: Path) -> None:
    with pytest.raises(SubscriptionsError):
        SubscriptionsSource(tmp_path / "nope.yaml").current()
