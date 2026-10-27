"""Причина, кто исправляет, группировка, затухание и оповещения внешних сервисов (W15-H3)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.domain import external_cause as cause
from app.domain import external_registry as reg
from app.domain import external_status as rules
from app.domain import external_vendor as vendor_rules
from app.domain.external_cause import Context, Diagnosis, Group, OpenCause
from app.domain.external_status import CheckResult, HttpFacts
from app.domain.system_status import hosting_ask

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
PROVIDERS: dict[str, str | None] = {
    "dialog-model": "anthropic",
    "qualifier-model": "anthropic",
    "fallback-model": "anthropic",
    "embed-model": "gemini",
    "judge-model": "anthropic",
}
SPECS = {s.key: s for s in reg.registry(PROVIDERS)}


def _diagnose(
    key: str, result: CheckResult, since: datetime | None = None, **ctx: Any
) -> Diagnosis:
    return cause.diagnose(SPECS[key], result, Context(providers=PROVIDERS, **ctx), since)


def _vendor_failure(kind: str | None, vendor: str = "anthropic") -> CheckResult:
    window = vendor_rules.VendorStats(
        calls=10, failures=10, last_error="401 AuthenticationError", last_error_kind=kind
    )
    return vendor_rules.vendor(vendor_rules.VendorFacts(vendor, True, window))


# --- один корень — одна строка ------------------------------------------------------------------


def test_rejected_key_names_the_vendor_and_lists_what_stops_working() -> None:
    d = _diagnose("vendor.anthropic", _vendor_failure("auth"), NOW - timedelta(minutes=7))
    assert d.state == "broken"
    assert d.cause == "key_rejected"
    assert d.headline == "Ключ Anthropic отклонён"
    assert d.affected == (
        "диалог с клиентом",
        "оценка лидов",
        "запасная модель",
        "проверка качества ответов",
    )
    assert (d.owner, d.action) == ("owner", "enter_key")
    assert d.more == ("write_owner", "disable_provider")


def test_two_services_with_one_root_are_one_group() -> None:
    erp_sync = CheckResult(
        "erp_sync", "fail", "Доступ не синхронизирован", cause="erp_not_connected"
    )
    erp_handoff = CheckResult(
        "erp_handoff", "fail", "Клиенты не переданы", cause="erp_not_connected"
    )
    items = [
        _diagnose("erp_sync", erp_sync, NOW - timedelta(minutes=3)),
        _diagnose("erp_handoff", erp_handoff, NOW - timedelta(minutes=9)),
    ]
    groups = cause.build_groups(items)
    assert len(groups) == 1
    only = groups[0]
    assert only.id == "erp:erp_not_connected"
    assert only.service_keys == ("erp_sync", "erp_handoff")
    assert only.since == NOW - timedelta(minutes=9)  # самое раннее «с …»
    assert only.state == "not_configured"


def test_different_vendors_do_not_merge() -> None:
    items = [
        _diagnose("vendor.anthropic", _vendor_failure("auth", "anthropic")),
        _diagnose("vendor.gemini", _vendor_failure("auth", "gemini")),
    ]
    assert [g.id for g in cause.build_groups(items)] == [
        "vendor.anthropic:key_rejected",
        "vendor.gemini:key_rejected",
    ]


def test_groups_are_sorted_broken_first_and_ok_is_left_out() -> None:
    ok = _diagnose("s3", rules.s3(HttpFacts(None, None, 5)))
    docling = _diagnose("docling", rules.docling(HttpFacts("unavailable", "refused")))
    langfuse = _diagnose("langfuse", rules.langfuse(rules.LangfuseFacts(configured=False)))
    groups = cause.build_groups([langfuse, ok, docling])
    assert [g.id for g in groups] == ["docling:server_down", "langfuse:disabled"]


def test_group_technical_details_are_masked_and_deduplicated() -> None:
    raw = "401 Error: Bearer sk-ant-abcdef123456789 rejected"
    result = CheckResult("vendor.anthropic", "fail", "x", error=raw, cause="key_rejected")
    d = _diagnose("vendor.anthropic", result)
    assert d.technical is not None
    assert "sk-ant-abcdef" not in d.technical
    assert "REDACTED" in d.technical
    twice = cause.build_groups([d, d])
    assert len(twice[0].technical) == 1


# --- статусы словами -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("result", "ctx", "state"),
    [
        (rules.telegram(rules.TelegramFacts(False, "polling"), NOW), {}, "not_configured"),
        (rules.docling(None), {}, "disabled"),
        (rules.docling(HttpFacts("unavailable", "x")), {}, "broken"),
        (rules.docling(HttpFacts(None, None, 5)), {}, "ok"),
        (rules.docling(HttpFacts("unavailable", "x")), {"disabled": True}, "disabled"),
        (rules.docling(HttpFacts("unavailable", "x")), {"never_checked": True}, "not_checked"),
        (rules.docling(HttpFacts(None, None, 5)), {"stale": True}, "not_checked"),
        (CheckResult("docling", "unknown", "?"), {}, "not_checked"),
        (_vendor_failure("other"), {}, "broken"),
        (
            vendor_rules.vendor(
                vendor_rules.VendorFacts(
                    "anthropic",
                    True,
                    vendor_rules.VendorStats(
                        calls=10, failures=3, last_error_kind="other", last_error="x"
                    ),
                )
            ),
            {},
            "degraded",
        ),
    ],
)
def test_state_word(result: CheckResult, ctx: dict[str, Any], state: str) -> None:
    key = result.key
    assert _diagnose(key, result, **ctx).state == state


def test_expected_on_stand_is_grey_for_causes_nobody_fixes_there() -> None:
    docling = rules.docling(HttpFacts("unavailable", "x"))
    token = rules.telegram(rules.TelegramFacts(False, "polling"), NOW)
    key = _vendor_failure("auth")
    assert _diagnose("docling", docling, stand=True).state == "expected"
    assert _diagnose("telegram", token, stand=True).state == "expected"
    assert _diagnose("vendor.anthropic", key, stand=True).state == "expected"
    # на проде — те же факты, но «Сломано» / «Не настроено»
    assert _diagnose("docling", docling, stand=False).state == "broken"
    assert _diagnose("telegram", token, stand=False).state == "not_configured"


def test_stand_does_not_hide_what_the_admin_fixes() -> None:
    smtp = rules.mail(
        rules.MailFacts(configured=True, probe_error="auth_failed"),
        NOW,
    )
    assert _diagnose("mail", smtp, stand=True).state == "broken"


# --- кто исправляет и действие ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "owner", "action"),
    [
        ("auth", "owner", "enter_key"),
        ("quota", "owner", "write_owner"),
        ("other", "provider", "recheck"),
    ],
)
def test_vendor_owner_and_primary_action(kind: str, owner: str, action: str) -> None:
    d = _diagnose("vendor.anthropic", _vendor_failure(kind))
    assert (d.owner, d.action) == (owner, action)
    assert "disable_provider" in d.more


def test_hosting_text_names_who_and_what_to_send_instead_of_ask_the_server_admin() -> None:
    result = rules.docling(HttpFacts("unavailable", "refused"))
    d = _diagnose("docling", result)
    assert d.owner == "hosting"
    assert d.action == "write_hosting"
    assert d.detail is not None
    assert "администратору сервера" not in d.detail
    assert d.detail == (
        "Сервис распознавания документов не запущен на сервере. Это настраивает тот, кто "
        "разворачивал Платформу (хостинг). Отправьте ему: «Запустить docling вместе с ансамблем»"
    )
    assert hosting_ask(d.detail) == "Запустить docling вместе с ансамблем"
    group = cause.build_groups([d])[0]
    assert group.message is not None
    assert "Запустить docling вместе с ансамблем" in group.message


def test_no_rule_text_sends_the_user_to_the_server_admin() -> None:
    samples = [
        rules.litellm(rules.GatewayFacts(HttpFacts("unavailable", "x"))),
        rules.litellm(rules.GatewayFacts(HttpFacts(None, None, 1), "disconnected")),
        rules.langfuse(rules.LangfuseFacts(True, HttpFacts("unavailable", "x"))),
        rules.langfuse(rules.LangfuseFacts(True, HttpFacts(None, None, 1), keys_ok=False)),
        rules.s3(HttpFacts("unavailable", "x")),
        rules.docling(HttpFacts("unavailable", "x")),
        rules.telegram(rules.TelegramFacts(True, "polling", error="timeout"), NOW),
        rules.telegram(rules.TelegramFacts(True, "webhook", config_url=""), NOW),
        rules.mail(
            rules.MailFacts(
                configured=True, queued=2, oldest_queued_at=NOW - timedelta(minutes=30)
            ),
            NOW,
        ),
        rules.TlsFacts("crm", "crm.example.uz", error="unavailable"),
    ]
    texts = [x.hint for x in samples if isinstance(x, CheckResult)]
    texts.append(rules.tls(samples[-1]).hint)  # type: ignore[arg-type]
    texts.append(rules.stale_summary(NOW - timedelta(minutes=30), NOW)[1])
    for text in texts:
        assert text is not None
        assert "администратору сервера" not in text
        assert "хостинг" in text
        assert hosting_ask(text)


def test_owner_message_for_rejected_key_is_ready_to_copy() -> None:
    d = _diagnose("vendor.anthropic", _vendor_failure("auth"), NOW - timedelta(minutes=20))
    message = cause.build_groups([d], tz="Asia/Tashkent")[0].message
    assert message is not None
    assert "Ключ Anthropic отклонён" in message
    assert "диалог с клиентом" in message
    assert "новый ключ" in message
    assert "27.10 13:40" in message  # с учётом часового пояса компании


def test_provider_side_failure_has_no_message_for_the_owner() -> None:
    d = _diagnose("vendor.anthropic", _vendor_failure("other"))
    assert cause.build_groups([d])[0].message is None


# --- затухание повторных проверок ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("failures", "minutes"), [(0, 1), (1, 1), (2, 2), (3, 5), (4, 15), (5, 15), (40, 15)]
)
def test_recheck_interval_decays_then_holds_at_fifteen(failures: int, minutes: int) -> None:
    assert cause.recheck_interval(failures) == timedelta(minutes=minutes)


def test_recheck_due_follows_the_schedule_with_a_clock_substitute() -> None:
    last = NOW
    # третий сбой подряд -> следующая проверка через 5 минут
    assert not cause.recheck_due(3, last, last + timedelta(minutes=4))
    assert cause.recheck_due(3, last, last + timedelta(minutes=5))
    # четвёртый и дальше -> раз в 15 минут
    assert not cause.recheck_due(9, last, last + timedelta(minutes=14))
    assert cause.recheck_due(9, last, last + timedelta(minutes=15))
    # допуск на дрожание расписания
    assert cause.recheck_due(2, last, last + timedelta(minutes=2) - timedelta(seconds=5))


# --- оповещения: одно «сломано», одно «восстановлено» ----------------------------------------


def _broken_group(since: datetime | None = None) -> Group:
    d = _diagnose("docling", rules.docling(HttpFacts("unavailable", "x")), since)
    return cause.build_groups([d])[0]


def _kinds(steps: list[cause.Step]) -> list[str]:
    return [s.kind for s in steps]


def test_no_alert_before_fifteen_minutes() -> None:
    group = _broken_group(since=NOW - timedelta(minutes=14))
    steps = cause.plan_alerts([group], {}, {"docling": "broken"}, NOW)
    assert _kinds(steps) == ["open"]


def test_one_alert_after_fifteen_minutes_and_none_on_later_passes() -> None:
    group = _broken_group(since=NOW - timedelta(minutes=16))
    first = cause.plan_alerts([group], {}, {"docling": "broken"}, NOW)
    assert _kinds(first) == ["open", "alert"]
    row = OpenCause(group.id, NOW - timedelta(minutes=16), NOW, ("docling",))
    later = cause.plan_alerts(
        [group], {group.id: row}, {"docling": "broken"}, NOW + timedelta(hours=3)
    )
    assert later == []


def test_alert_waits_on_an_existing_row_until_the_threshold() -> None:
    group = _broken_group(since=NOW - timedelta(minutes=2))
    row = OpenCause(group.id, NOW - timedelta(minutes=2), None, ("docling",))
    assert cause.plan_alerts([group], {group.id: row}, {"docling": "broken"}, NOW) == []
    at_15 = NOW + timedelta(minutes=13)
    steps = cause.plan_alerts([group], {group.id: row}, {"docling": "broken"}, at_15)
    assert _kinds(steps) == ["alert"]


def test_recovery_closes_the_row_with_one_restore() -> None:
    row = OpenCause("docling:server_down", NOW - timedelta(minutes=40), NOW, ("docling",))
    steps = cause.plan_alerts([], {row.cause_key: row}, {"docling": "ok"}, NOW)
    assert steps == [cause.Step("restore", row.cause_key)]


def test_not_checked_and_degraded_keep_the_row_open() -> None:
    row = OpenCause("docling:server_down", NOW - timedelta(minutes=40), NOW, ("docling",))
    for state in ("not_checked", "degraded"):
        assert cause.plan_alerts([], {row.cause_key: row}, {"docling": state}, NOW) == []


@pytest.mark.parametrize("state", ["expected", "disabled", "not_configured"])
def test_switched_off_or_expected_closes_quietly_without_a_restore_message(state: str) -> None:
    row = OpenCause("docling:server_down", NOW - timedelta(minutes=40), NOW, ("docling",))
    steps = cause.plan_alerts([], {row.cause_key: row}, {"docling": state}, NOW)  # type: ignore[dict-item]
    assert _kinds(steps) == ["close"]


def test_expected_and_disabled_groups_never_alert() -> None:
    docling = rules.docling(HttpFacts("unavailable", "x"))
    expected = cause.build_groups(
        [_diagnose("docling", docling, NOW - timedelta(days=1), stand=True)]
    )
    assert cause.plan_alerts(expected, {}, {"docling": "expected"}, NOW) == []
    off = cause.build_groups(
        [_diagnose("docling", docling, NOW - timedelta(days=1), disabled=True)]
    )
    assert cause.plan_alerts(off, {}, {"docling": "disabled"}, NOW) == []


def test_alert_texts_have_no_raw_error_and_name_the_owner() -> None:
    d = _diagnose("vendor.anthropic", _vendor_failure("auth"), NOW - timedelta(minutes=20))
    group = cause.build_groups([d])[0]
    text = cause.broken_alert(group, group.since or NOW, NOW, "UTC")
    assert text.subject == "⚠️ Сломано: Ключ Anthropic отклонён"
    plain = text.plain
    assert "владелец компании" in plain
    assert "AuthenticationError" not in plain
    assert "уже 20 мин" in plain
    restored = cause.restored_alert(group.headline, timedelta(minutes=35))
    assert restored.subject == "✅ Восстановлено: Ключ Anthropic отклонён"
    assert "35 мин" in restored.plain
