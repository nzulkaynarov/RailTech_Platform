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
    ("failures", "minutes"), [(0, 1), (1, 1), (2, 2), (3, 5), (4, 7), (5, 7), (40, 7)]
)
def test_recheck_interval_decays_then_holds_at_seven(failures: int, minutes: int) -> None:
    assert cause.recheck_interval(failures) == timedelta(minutes=minutes)


def test_recheck_due_follows_the_schedule_with_a_clock_substitute() -> None:
    last = NOW
    # третий сбой подряд -> следующая проверка через 5 минут
    assert not cause.recheck_due(3, last, last + timedelta(minutes=4))
    assert cause.recheck_due(3, last, last + timedelta(minutes=5))
    # четвёртый и дальше -> раз в 7 минут: проверка точно на 15-й минуте полосы (0, 1, 3, 8, 15)
    assert not cause.recheck_due(9, last, last + timedelta(minutes=6))
    assert cause.recheck_due(9, last, last + timedelta(minutes=7))
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
    assert steps == []  # короткий провал: ни записи, ни оповещения


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
    began = NOW - timedelta(minutes=6)
    steps = cause.plan_alerts([], {row.cause_key: row}, {"docling": "ok"}, NOW, {"docling": began})
    assert steps == [cause.Step("restore", row.cause_key, began)]


def test_not_checked_and_degraded_keep_the_row_open() -> None:
    row = OpenCause("docling:server_down", NOW - timedelta(minutes=40), NOW, ("docling",))
    for state in ("not_checked", "degraded", "unstable"):
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
    assert "администратор вводит новый ключ; ключ и оплата — у владельца." in plain
    assert "AuthenticationError" not in plain
    assert "уже 20 мин" in plain
    restored = cause.restored_alert(group.headline, timedelta(minutes=35))
    assert restored.subject == "✅ Восстановлено: Ключ Anthropic отклонён"
    assert "35 мин" in restored.plain


# --- «с {время}» и порог 15 минут считаются от начала полосы fail ---------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("fail", NOW - timedelta(minutes=2)),  # off/warn несколько дней → fail: «сломано» 2 мин
        ("warn", NOW - timedelta(days=3)),
        ("off", NOW - timedelta(days=3)),
        ("unknown", NOW - timedelta(days=3)),
    ],
)
def test_since_for_broken_starts_at_the_fail_streak(status: str, expected: datetime) -> None:
    got = cause.since_for(
        status,  # type: ignore[arg-type]
        fail_since=NOW - timedelta(minutes=2),
        unhealthy_since=NOW - timedelta(days=3),
        incident_started=None,
    )
    assert got == expected


def test_since_for_falls_back_to_the_incident_and_then_to_the_unhealthy_start() -> None:
    incident = NOW - timedelta(minutes=9)
    assert (
        cause.since_for("fail", fail_since=None, unhealthy_since=NOW, incident_started=incident)
        == incident
    )
    assert (
        cause.since_for("fail", fail_since=None, unhealthy_since=NOW, incident_started=None) == NOW
    )


@pytest.mark.parametrize("earlier", ["off", "warn"])
def test_a_service_that_was_off_or_degraded_for_days_does_not_alert_at_once_on_fail(
    earlier: str,
) -> None:
    """off/degraded → fail: до оповещения 15 минут от падения, а не «уже 3 дн»."""
    fail_started = NOW - timedelta(minutes=3)
    since = cause.since_for(
        "fail",
        fail_since=fail_started,
        unhealthy_since=NOW - timedelta(days=3),
        incident_started=None,
    )
    group = cause.build_groups(
        [_diagnose("docling", rules.docling(HttpFacts("unavailable", "x")), since)]
    )[0]
    assert group.since == fail_started
    states: dict[str, cause.State] = {"docling": "broken"}
    assert cause.plan_alerts([group], {}, states, NOW) == []  # 3 мин fail: ещё не «Сломано»
    later = fail_started + cause.ALERT_AFTER
    assert [s.kind for s in cause.plan_alerts([group], {}, states, later)] == ["open", "alert"]
    assert earlier  # параметр описывает, что было до падения


# --- дребезг: «Нестабильно», 15 минут fail, 5 минут ok, одно «Сломано» в сутки ----


def _fail_diag(fail_for: timedelta | None, **ctx: Any) -> Diagnosis:
    return _diagnose(
        "docling",
        rules.docling(HttpFacts("unavailable", "x")),
        NOW - (fail_for or timedelta(0)),
        fail_for=fail_for,
        **ctx,
    )


@pytest.mark.parametrize(
    ("fail_minutes", "state"),
    [(0, "unstable"), (1, "unstable"), (14, "unstable"), (15, "broken"), (90, "broken")],
)
def test_fail_is_broken_only_after_fifteen_continuous_minutes(
    fail_minutes: int, state: str
) -> None:
    assert _fail_diag(timedelta(minutes=fail_minutes)).state == state


def test_a_short_failure_is_unstable_yellow_and_never_alertable() -> None:
    d = _fail_diag(timedelta(minutes=3))
    assert d.state == "unstable"
    assert (d.owner, d.action) == ("hosting", "write_hosting")
    group = cause.build_groups([d])[0]
    assert group.state == "unstable"
    assert group.message is None
    steps = cause.plan_alerts([group], {}, {"docling": "unstable"}, NOW)
    assert steps == []


def test_flapping_service_is_unstable_without_a_continuous_fail() -> None:
    ok = rules.docling(HttpFacts(None, None, 5))
    d = _diagnose("docling", ok, None, flaps_24h=7, flaps_recent=4)
    assert d.state == "unstable"
    assert d.cause == "flapping"
    assert d.cause_key == "docling:flapping"
    assert d.headline.endswith("провалов за сутки: 7")
    assert cause.plan_alerts(cause.build_groups([d]), {}, {"docling": "unstable"}, NOW) == []
    quiet = _diagnose("docling", ok, None, flaps_24h=2, flaps_recent=2)
    assert quiet.state == "ok"


def test_stand_greys_out_an_unstable_hosting_failure() -> None:
    assert _fail_diag(timedelta(minutes=2), stand=True).state == "expected"


def test_restore_waits_for_five_continuous_ok_minutes() -> None:
    row = OpenCause("docling:server_down", NOW - timedelta(minutes=60), NOW, ("docling",))
    states: dict[str, cause.State] = {"docling": "ok"}
    for minutes, due in ((1, False), (4, False), (5, True), (30, True)):
        began = NOW - timedelta(minutes=minutes)
        steps = cause.plan_alerts([], {row.cause_key: row}, states, NOW, {"docling": began})
        assert [s.kind for s in steps] == (["restore"] if due else [])
    # нет данных о начале ok — не восстановлено
    assert cause.plan_alerts([], {row.cause_key: row}, states, NOW, {}) == []


def test_a_short_failure_after_recovery_does_not_open_a_second_alert() -> None:
    """ok 3 мин → fail 2 мин: запись всё ещё открыта, нового «Сломано» и «Восстановлено» нет."""
    row = OpenCause("docling:server_down", NOW - timedelta(minutes=60), NOW, ("docling",))
    blip = _fail_diag(timedelta(minutes=2))
    steps = cause.plan_alerts(
        cause.build_groups([blip]), {row.cause_key: row}, {"docling": "unstable"}, NOW
    )
    assert steps == []


def test_second_outage_within_a_day_is_suppressed_not_repeated() -> None:
    group = _broken_group(since=NOW - timedelta(minutes=20))
    fresh = cause.plan_alerts([group], {}, {"docling": "broken"}, NOW, recently_alerted={group.id})
    assert _kinds(fresh) == ["open", "suppress"]
    row = OpenCause(group.id, NOW - timedelta(minutes=20), None, ("docling",), suppressed_at=NOW)
    later = cause.plan_alerts(
        [group],
        {group.id: row},
        {"docling": "broken"},
        NOW + timedelta(hours=1),
        recently_alerted={group.id},
    )
    assert later == []  # подавленную причину повторно не оценивают
    # через сутки после прошлого «Сломано» — снова одно сообщение
    after_day = cause.plan_alerts([group], {}, {"docling": "broken"}, NOW, recently_alerted=set())
    assert _kinds(after_day) == ["open", "alert"]


def test_alert_text_carries_the_flap_count() -> None:
    group = cause.build_groups([_fail_diag(timedelta(minutes=20), flaps_24h=5)])[0]
    plain = cause.broken_alert(group, group.since or NOW, NOW, "UTC").plain
    assert "5-й провал" in plain


# --- сводка после подавления, блип при восстановлении, «15 минут» по проверкам (W15-H3b) ----------


def test_the_schedule_checks_the_fail_on_the_fifteenth_minute_not_earlier() -> None:
    """Сбой с 0-й минуты: проверки на 0, 1, 3, 8, 15; четыре провала за 8 минут — не «Сломано»."""
    at_minute = 0
    checks = [0]
    for failures in range(1, 8):
        at_minute += int(cause.recheck_interval(failures).total_seconds() // 60)
        checks.append(at_minute)
        if at_minute >= 15:
            break
    assert checks == [0, 1, 3, 8, 15]
    assert checks[3] - checks[0] < 15  # четыре провала за 8 минут
    assert checks[4] - checks[0] >= 15  # пятая проверка — ровно 15-я минута


def test_suppressed_cause_is_announced_once_after_the_day_with_the_repeats() -> None:
    group = _broken_group(since=NOW - timedelta(minutes=40))
    row = OpenCause(group.id, NOW - timedelta(minutes=40), None, ("docling",), suppressed_at=NOW)
    # сутки с прошлого «Сломано» ещё не прошли — подавлено, повторно не оценивается
    assert (
        cause.plan_alerts(
            [group], {group.id: row}, {"docling": "broken"}, NOW, recently_alerted={group.id}
        )
        == []
    )
    # сутки прошли, сбой всё ещё непрерывный — одно «Сломано» со сводкой, без новой записи
    steps = cause.plan_alerts([group], {group.id: row}, {"docling": "broken"}, NOW)
    assert _kinds(steps) == ["alert"]
    after = OpenCause(group.id, row.started_at, NOW, ("docling",), suppressed_at=NOW)
    assert cause.plan_alerts([group], {group.id: after}, {"docling": "broken"}, NOW) == []


def test_summary_line_counts_the_failures_since_the_previous_message() -> None:
    group = cause.build_groups([_fail_diag(timedelta(minutes=20))])[0]
    plain = cause.broken_alert(
        group,
        group.since or NOW,
        NOW,
        "UTC",
        repeats=3,
        since_previous=timedelta(hours=24, minutes=5),
    ).plain
    assert "Нестабилен: 3 провала с прошлого сообщения (1 дн назад)." in plain
    quiet = cause.broken_alert(group, group.since or NOW, NOW, "UTC", repeats=1).plain
    assert "Нестабилен" not in quiet


def _rows(*pairs: tuple[int, str]) -> list[tuple[str, datetime]]:
    """Проверки новые первыми: (минут назад, статус)."""
    return [(status, NOW - timedelta(minutes=ago)) for ago, status in pairs]


def test_ok_run_starts_after_the_last_real_non_ok_stretch() -> None:
    rows = _rows((0, "ok"), (1, "ok"), (2, "ok"), (3, "fail"), (4, "fail"), (30, "fail"))
    assert cause.ok_run_start(rows) == NOW - timedelta(minutes=2)
    assert cause.ok_run_start(_rows((0, "fail"), (1, "ok"))) is None  # сейчас не ok
    assert cause.ok_run_start([]) is None


def test_a_short_blip_or_warn_does_not_reset_the_recovery_clock() -> None:
    # ok 9..6 мин назад, провал 5, ok 4..0: провал между двумя ok отсчёт не сбрасывает
    rows = _rows(
        (0, "ok"), (1, "ok"), (2, "ok"), (3, "ok"), (4, "ok"), (5, "fail"),
        (6, "ok"), (7, "ok"), (8, "ok"), (9, "ok"), (10, "fail"), (11, "fail"),
    )  # fmt: skip
    assert cause.ok_run_start(rows) == NOW - timedelta(minutes=9)
    warn = _rows((0, "ok"), (1, "ok"), (2, "warn"), (3, "ok"), (4, "ok"), (5, "fail"))
    assert cause.ok_run_start(warn) == NOW - timedelta(minutes=4)


def test_a_long_gap_between_ok_checks_is_not_a_blip() -> None:
    # fail 5 минут назад, соседние ok — через 8 мин: за это время сервис мог лежать — отсчёт заново
    rows = _rows((0, "ok"), (1, "ok"), (2, "ok"), (3, "ok"), (4, "ok"), (5, "fail"), (12, "ok"))
    assert cause.ok_run_start(rows) == NOW - timedelta(minutes=4)


# --- часовая проба моделей — источник причины в центре, а не второй отправитель ----


def test_hourly_probe_problem_becomes_the_vendor_cause_even_without_traffic() -> None:
    quiet = vendor_rules.VendorStats()
    probe = (
        ("dialog-model", "провайдер отклонил ключ — проверьте ключ API; бот не отвечает"),
        ("qualifier-model", "провайдер отклонил ключ — проверьте ключ API; бот не отвечает"),
    )
    result = vendor_rules.vendor(vendor_rules.VendorFacts("anthropic", True, quiet, probe=probe))
    assert (result.status, result.cause) == ("fail", "key_rejected")
    d = _diagnose("vendor.anthropic", result, None, fail_for=timedelta(minutes=20))
    assert d.state == "broken"
    assert d.headline == "Ключ Anthropic отклонён"  # одна причина на провайдера, не по алиасу
    assert (d.owner, d.action) == ("owner", "enter_key")


def test_hourly_probe_credits_problem_is_the_quota_cause() -> None:
    probe = (("dialog-model", "закончились кредиты или квота у провайдера — пополните баланс"),)
    result = vendor_rules.vendor(
        vendor_rules.VendorFacts("anthropic", True, vendor_rules.VendorStats(), probe=probe)
    )
    assert result.cause == "quota"


def test_no_probe_problem_leaves_the_log_based_verdict_alone() -> None:
    result = vendor_rules.vendor(
        vendor_rules.VendorFacts("anthropic", True, vendor_rules.VendorStats())
    )
    assert result.status == "ok"


# --- причины, которые сами не проходят, проверяются реже ---------------------------------------


@pytest.mark.parametrize(
    "slow", ["key_rejected", "quota", "token_rejected", "smtp_auth_failed", "smtp_rejected"]
)
def test_causes_that_do_not_heal_themselves_are_rechecked_every_fifteen_minutes(slow: str) -> None:
    for failures in (1, 2, 3, 4, 9):
        assert cause.recheck_interval(failures, slow) == timedelta(minutes=15)
    assert cause.recheck_interval(1, "network") == timedelta(minutes=1)  # дешёвые сетевые — 1/2/5/7
    assert cause.recheck_interval(4, None) == timedelta(minutes=7)
    last = NOW
    assert not cause.recheck_due(1, last, last + timedelta(minutes=14), "smtp_auth_failed")
    assert cause.recheck_due(1, last, last + timedelta(minutes=15), "smtp_auth_failed")


# --- архив WAL, Redis и шина на общей политике (W15-H8b, B-004) ---------------------------------


def test_bus_dlq_is_broken_only_after_fifteen_minutes_and_sends_the_admin_to_the_bus_journal() -> (
    None
):
    from app.domain import external_infra as infra

    dlq = infra.bus_dlq(infra.BusDlqFacts(dead=3, failed=0, last_error="eds/letter.created: 500"))
    short = _diagnose("bus_dlq", dlq, NOW - timedelta(minutes=5), fail_for=timedelta(minutes=5))
    assert short.state == "unstable"  # меньше 15 минут — ещё «Нестабильно», без оповещения
    long = _diagnose("bus_dlq", dlq, NOW - timedelta(minutes=20), fail_for=timedelta(minutes=20))
    assert long.state == "broken"
    assert (long.owner, long.action, long.more) == ("admin", "open_bus", ("recheck",))
    assert long.headline == "Шина: не доставлено: 3"
    group = cause.build_groups([long])[0]
    assert cause.plan_alerts([group], {}, {"bus_dlq": "broken"}, NOW)  # одно «Сломано»


def test_bus_dlq_ok_has_no_cause() -> None:
    from app.domain import external_infra as infra

    ok = infra.bus_dlq(infra.BusDlqFacts(0, 0))
    assert _diagnose("bus_dlq", ok).state == "ok"


@pytest.mark.parametrize("key", ["wal_archive", "redis_broker", "redis_cache"])
def test_infrastructure_rows_are_fixed_by_hosting(key: str) -> None:
    from app.domain import external_infra as infra

    result = (
        infra.wal_archive(infra.WalFacts(None, NOW - timedelta(hours=2), NOW), NOW)
        if key == "wal_archive"
        else infra.redis(infra.RedisFacts(key, error="ConnectionRefusedError"), NOW)
    )
    d = _diagnose(key, result, NOW - timedelta(minutes=30), fail_for=timedelta(minutes=30))
    assert d.state == "broken"
    assert d.owner == "hosting"
    assert d.action == "write_hosting"
    assert hosting_ask(d.detail)  # готовый текст «что передать хостингу»


def test_unreadable_wal_is_not_checked_not_broken() -> None:
    from app.domain import external_infra as infra

    d = _diagnose("wal_archive", infra.wal_archive(infra.WalFacts(error="AccessDenied"), NOW))
    assert d.state == "not_checked"
    assert d.owner is None
