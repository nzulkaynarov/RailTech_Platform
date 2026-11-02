"""Состояния письма-обращения, адресаты и цепочки (W18A-P2-3): чистые правила, адреса
вымышленные."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import inbound_mail_flow as flow

BOX = "inbox@company.test"
NOBOX = "nobody@company.test"  # маркер случая «адрес ящика не задан»
STAFF = {"ivanov@company.test": 11, "petrov@company.test": 12, "sidorov@company.test": 13}


@pytest.mark.parametrize(
    ("to", "cc", "rule", "personal", "assignee", "to_staff", "cc_staff"),
    [
        # коллега в «Кому», общий ящик в копии: письмо ему лично
        (["ivanov@company.test"], [BOX], True, True, 11, [11], []),
        # правило выключено: всё в «Новые», сотрудники только показаны
        (["ivanov@company.test"], [BOX], False, False, None, [11], []),
        # общий ящик в «Кому» — обычное письмо первой линии
        ([BOX, "ivanov@company.test"], [], True, False, None, [11], []),
        # общий ящик и в «Кому», и в копии: считаем адресованным ящику
        ([BOX, "ivanov@company.test"], [BOX], True, False, None, [11], []),
        # нет сотрудника в «Кому»: сотрудник только в копии — не лично
        (["client@example.test"], [BOX, "petrov@company.test"], True, False, None, [], [12]),
        # несколько сотрудников в «Кому»: первый — исполнитель, остальные — соадресаты
        (
            ["petrov@company.test", "ivanov@company.test", "client@example.test"],
            [BOX, "sidorov@company.test"],
            True,
            True,
            12,
            [12, 11],
            [13],
        ),
        # регистр адреса, повтор и сотрудник и в «Кому», и в копии
        (["IVANOV@Company.test"], [BOX, "ivanov@company.test"], True, True, 11, [11], []),
        # общего ящика нет ни в «Кому», ни в копии (скрытая копия, рассылка): не угадываем
        (["ivanov@company.test"], [], True, False, None, [11], []),
        # ящик не задан (опрос без логина): личного адресования нет
        (["ivanov@company.test"], [NOBOX], True, False, None, [11], []),
    ],
)
def test_classify_recipients(
    to: list[str],
    cc: list[str],
    rule: bool,
    personal: bool,
    assignee: int | None,
    to_staff: list[int],
    cc_staff: list[int],
) -> None:
    mailbox = None if NOBOX in cc else BOX
    out = flow.classify_recipients(to, cc, mailbox, STAFF, rule_on=rule)
    assert (out.personal, out.assignee_id) == (personal, assignee)
    assert (list(out.to_staff), list(out.cc_staff)) == (to_staff, cc_staff)


@pytest.mark.parametrize(
    ("in_reply_to", "references", "expected"),
    [
        (None, None, []),
        ("<a@x.test>", None, ["a@x.test"]),
        # ближайшее письмо цепочки — первым: последнее в References
        ("<c@x.test>", "<a@x.test> <b@x.test> <c@x.test>", ["c@x.test", "b@x.test", "a@x.test"]),
        (None, "<a@x.test>\r\n <b@x.test>", ["b@x.test", "a@x.test"]),
        # мусор и повторы не ломают разбор
        ("не id", "<a@x.test> <a@x.test> broken", ["a@x.test"]),
    ],
)
def test_thread_ids(in_reply_to: str | None, references: str | None, expected: list[str]) -> None:
    assert flow.thread_ids(in_reply_to, references) == expected


def test_thread_ids_are_capped() -> None:
    refs = " ".join(f"<m{n}@x.test>" for n in range(100))
    assert len(flow.thread_ids(None, refs)) == flow.MAX_THREAD_IDS


@pytest.mark.parametrize(
    ("status", "assignee", "actor", "expected"),
    [
        ("new", None, 5, "take"),
        ("new", 7, 5, "take"),  # вернулось «ответом в цепочке»: прежний исполнитель — справка
        ("in_work", 5, 5, "mine"),
        ("registering", 5, 5, "mine"),
        ("in_work", 7, 5, "other"),
        ("registering", 7, 5, "other"),
        ("done", 5, 5, "closed"),
        ("spam", None, 5, "closed"),
    ],
)
def test_claim_of(status: str, assignee: int | None, actor: int, expected: str) -> None:
    assert flow.claim_of(status, assignee, actor) == expected


@pytest.mark.parametrize(
    ("status", "outcome", "expected"),
    [
        ("done", "archived", True),
        ("done", "replied", True),
        ("done", "registered", False),
        ("done", "lead", False),
        ("in_work", None, True),
        ("registering", None, False),
        ("new", None, False),
        ("spam", None, False),
    ],
)
def test_can_return_to_new(status: str, outcome: str | None, expected: bool) -> None:
    assert flow.can_return(status, outcome) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("done", "new"),  # «Разобрано» → снова «Новое (ответ в цепочке)»
        ("new", "new"),
        ("in_work", "in_work"),
        ("registering", "registering"),
        ("spam", "spam"),
    ],
)
def test_status_after_thread_reply(status: str, expected: str) -> None:
    assert flow.status_after_reply(status) == expected


def test_eds_confirmation_overdue() -> None:
    now = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
    limit = timedelta(minutes=flow.EDS_CONFIRM_MINUTES)
    assert flow.eds_waiting("registering", now - limit + timedelta(seconds=1), now) is False
    assert flow.eds_waiting("registering", now - limit, now) is True
    assert flow.eds_waiting("registering", None, now) is False
    assert flow.eds_waiting("in_work", now - limit * 2, now) is False


@pytest.mark.parametrize(
    ("to", "cc", "sender", "expected"),
    [
        # «Ответить всем»: копия — все остальные, кроме общего ящика и самого отправителя
        (
            ["inbox@company.test"],
            ["petrov@company.test"],
            "client@example.test",
            ["petrov@company.test"],
        ),
        (
            ["inbox@company.test", "Client@Example.test", "boss@example.test"],
            ["petrov@company.test", "petrov@company.test"],
            "client@example.test",
            ["boss@example.test", "petrov@company.test"],
        ),
        ([BOX], [], "client@example.test", []),
    ],
)
def test_reply_all_copy(to: list[str], cc: list[str], sender: str, expected: list[str]) -> None:
    assert flow.reply_all_copy(to, cc, BOX, sender) == expected


@pytest.mark.parametrize(
    ("full", "user", "assignee", "personal", "staff", "visible"),
    [
        (True, 1, None, False, [], True),  # первая линия видит всё
        (False, 1, 1, False, [], True),  # исполнитель
        (False, 2, 1, True, [2, 3], True),  # соадресат письма «лично»
        (False, 2, 1, False, [2, 3], False),  # не лично: названный в письме сотрудник не видит
        (False, 4, 1, True, [2, 3], False),  # чужой
    ],
)
def test_participant_visibility(
    full: bool, user: int, assignee: int | None, personal: bool, staff: list[int], visible: bool
) -> None:
    assert flow.can_see(full, user, assignee, personal, staff) is visible
