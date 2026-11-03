"""Письмо общего ящика как обращение (W18A-P2-3): состояния, «в работе», адресаты, цепочки.

Чистые функции без I/O (CONVENTIONS.md §4). Состояния: «Новое» (`new`) → «В работе» (`in_work`:
исполнитель и время) → «Регистрируется» (`registering`: ВХ создаётся в EDS, ждём событие) →
«Разобрано» (`done` + итог `outcome`: ВХ, лид, ответ отправлен, архив); `spam` — «Подозрительные»
(P2-2). Эталоны: Front, Help Scout (кто ведёт письмо, «Take over»), Zendesk (статусы и
представления);
адресаты — Front и Help Scout (коллега в «Кому», общий ящик в копии), 1С:Документооборот и Directum
(«Адресат» и «Для сведения»).
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

Status = Literal["new", "in_work", "registering", "done", "spam"]
Outcome = Literal["registered", "lead", "replied", "archived", "price", "handled"]
Claim = Literal["take", "mine", "other", "closed"]

STATUSES: Final[tuple[str, ...]] = ("new", "in_work", "registering", "done", "spam")
OUTCOMES: Final[tuple[str, ...]] = ("registered", "lead", "replied", "archived", "price", "handled")
#: Сколько ждём событие EDS о регистрации, прежде чем показать «ждёт подтверждения EDS».
EDS_CONFIRM_MINUTES: Final = 10
MAX_THREAD_IDS: Final = 30
MAX_COPY: Final = 20
PERSONAL_LABEL_MAX: Final = 80
PERSONAL_LABEL_DEFAULT: Final = "Адресовано лично"

_MSG_ID: Final = re.compile(r"<([^<>\s]+)>")


@dataclass(frozen=True, slots=True)
class Recipients:
    """Сотрудники из «Кому» и копии (порядок письма) и решение «адресовано лично»."""

    to_staff: tuple[int, ...]
    cc_staff: tuple[int, ...]
    personal: bool
    assignee_id: int | None


def _addrs(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        addr = value.strip().lower()
        if addr and addr not in out:
            out.append(addr)
    return out


def classify_recipients(
    to: Sequence[str],
    cc: Sequence[str],
    mailbox: str | None,
    staff: Mapping[str, int],
    *,
    rule_on: bool,
) -> Recipients:
    """Сопоставить адреса с сотрудниками (`staff`: email в нижнем регистре → id активного
    пользователя) и решить, адресовано ли письмо лично.

    Лично — правило включено, в «Кому» есть сотрудник, а общий ящик (логин приёма) только в копии.
    Ящик в «Кому» или вне заголовков (скрытая копия, рассылка) — обычное письмо первой линии: по
    этим признакам личный адресат не определить. Исполнитель — первый сотрудник в «Кому», остальные
    — соадресаты; сотрудники из копии — «для сведения».
    """
    to_list, cc_list = _addrs(to), _addrs(cc)
    box = (mailbox or "").strip().lower()
    to_staff = [staff[a] for a in to_list if a in staff]
    to_staff = list(dict.fromkeys(to_staff))
    cc_staff = [staff[a] for a in cc_list if a in staff and staff[a] not in to_staff]
    cc_staff = list(dict.fromkeys(cc_staff))
    personal = bool(rule_on and to_staff and box and box in cc_list and box not in to_list)
    return Recipients(tuple(to_staff), tuple(cc_staff), personal, to_staff[0] if personal else None)


def thread_ids(in_reply_to: str | None, references: str | None) -> list[str]:
    """Message-ID письма-родителя и цепочки: ближайшее первым (`In-Reply-To`, затем `References`
    с конца), без повторов; мусор в заголовках пропускается."""
    found = [m.group(1) for m in _MSG_ID.finditer(in_reply_to or "")]
    found += list(reversed([m.group(1) for m in _MSG_ID.finditer(references or "")]))
    return list(dict.fromkeys(found))[:MAX_THREAD_IDS]


def claim_of(status: str, assignee_id: int | None, actor_id: int) -> Claim:
    """Что значит действие `actor_id` над письмом: взять (оно ничьё), продолжить своё, чужое
    «в работе» (409 «уже в работе у …») или письмо уже разобрано/подозрительное."""
    if status == "new":
        return "take"
    if status in ("in_work", "registering"):
        return "mine" if assignee_id == actor_id else "other"
    return "closed"


def can_return(status: str, outcome: str | None) -> bool:
    """«Вернуть в Новые»: своё «в работе» и разобранное архивом, ответом или «прайс загружен»."""
    if status == "in_work":
        return True
    return status == "done" and outcome in ("archived", "replied", "price", "handled")


def status_after_reply(status: str) -> str:
    """Входящее письмо в цепочке: «Разобрано» снова «Новое (ответ в цепочке)», остальное не
    меняется."""
    return "new" if status == "done" else status


def eds_waiting(status: str, registering_at: datetime | None, now: datetime) -> bool:
    """Регистрация начата, а событие EDS не пришло за `EDS_CONFIRM_MINUTES`: «ждёт
    подтверждения»."""
    if status != "registering" or registering_at is None:
        return False
    return now - registering_at >= timedelta(minutes=EDS_CONFIRM_MINUTES)


def reply_all_copy(
    to: Sequence[str], cc: Sequence[str], mailbox: str | None, sender: str
) -> list[str]:
    """«Ответить всем»: копия — все адреса письма, кроме самого общего ящика и отправителя (он — в
    «Кому» ответа). «Ответить» без «всем» копии не имеет."""
    skip = {(mailbox or "").strip().lower(), sender.strip().lower()}
    return [a for a in _addrs([*to, *cc]) if a not in skip][:MAX_COPY]


def can_see(
    full: bool, user_id: int, assignee_id: int | None, personal: bool, staff: Iterable[int]
) -> bool:
    """Кто видит письмо: первая линия (`mail_inbox`) — всё; остальные сотрудники — письмо, где они
    исполнитель, и письмо «лично», где названы (соадресаты и «для сведения»)."""
    if full or assignee_id == user_id:
        return True
    return personal and user_id in set(staff)


def chain_addresses(
    messages: Iterable[tuple[str, Sequence[str], Sequence[str]]], mailbox: str | None
) -> list[str]:
    """Адреса цепочки по порядку: отправители, «Кому» и копии её писем (`from`, `to`, `cc`), без
    общего ящика и повторов. Только они годятся адресатом ответа (W18A-P2-3)."""
    box = (mailbox or "").strip().lower()
    seen: dict[str, None] = {}
    for sender, to, cc in messages:
        for addr in (sender, *to, *cc):
            low = addr.strip().lower()
            if low and low != box:
                seen.setdefault(low)
    return list(seen)


def is_new_participant(sender: str, known: Iterable[str]) -> bool:
    """Письмо в цепочке от адреса, которого в ней ещё не было (подмена `From`, пересылка)."""
    return sender.strip().lower() not in {a.strip().lower() for a in known}


def reply_default(root_sender: str, latest_sender: str, latest_new: bool) -> str:
    """Кому ответ по умолчанию (Zendesk, Help Scout): отправителю корня цепочки; последнему письму
    — только если его адрес уже был в цепочке, иначе подделка `From` увела бы ответ."""
    return root_sender if latest_new or not latest_sender else latest_sender
