"""Папки общего ящика и загрузка истории (W18A-P2-2): чистые правила без I/O.

* **Папки.** Опрашиваются папки из настройки приёма (по умолчанию одна — INBOX). Имена у
  провайдеров разные («Spam», «Junk», «[Gmail]/Spam», «Спам» в modified UTF-7), поэтому не
  хардкодятся: «Найти папки» показывает ответ IMAP `LIST`, спам-папку подсказывает флаг `\\Junk`
  (RFC 6154), иначе выбирает человек.
* **Спам.** Письмо из спам-папки ложится в очередь со статусом `spam` («Подозрительные», не «Мои
  задачи»); найдено в обычной папке (переложили из «Спама» во «Входящие») — становится `new`.
* **История.** «Загрузить письма за период» берёт письма за 7–90 дней, не больше `HISTORY_LIMIT`
  за раз (новые раньше). Письмо старше `TASK_WINDOW_DAYS` помечается «из истории»: оно в списке
  «Входящая почта», но не строкой «Моих задач».
"""

import base64
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

#: Строки «Моих задач» — только для писем за последние дни; старше (из загрузки истории) — в списке.
TASK_WINDOW_DAYS: Final = 3
#: Периоды «Загрузить письма за период» (дней).
HISTORY_DAYS: Final[tuple[int, ...]] = (7, 14, 30, 90)
#: Писем за одну загрузку истории — больше не берём (новые раньше), итог говорит об этом словами.
HISTORY_LIMIT: Final = 2000
#: Папок для опроса — не больше (каждая — отдельный вход в ящик раз в 2 минуты).
MAX_FOLDERS: Final = 10
DEFAULT_FOLDER: Final = "INBOX"

_LIST_LINE: Final = re.compile(
    rb'^\((?P<flags>[^)]*)\) (?P<delim>"(?:[^"\\]|\\.)*"|NIL) (?P<name>.*)$'
)
_JUNK_NAMES: Final = frozenset({"spam", "junk", "спам", "нежелательная почта", "bulk mail"})


@dataclass(frozen=True, slots=True)
class FolderSetting:
    """Папка в настройке приёма: имя как на сервере (modified UTF-7) и «это спам»."""

    name: str
    spam: bool = False


@dataclass(frozen=True, slots=True)
class ServerFolder:
    """Папка из ответа `LIST`: имя для `EXAMINE`, подпись для человека, флаги."""

    name: str
    label: str
    junk: bool
    selectable: bool


def is_history(sent_at: datetime | None, now: datetime) -> bool:
    """Письмо из загрузки истории — «из истории», если старше окна задач или без даты.

    Без даты — тоже «из истории»: свежие письма уже забрал обычный опрос (первый опрос берёт те же
    `TASK_WINDOW_DAYS` дней), дубля по Message-ID нет, а «Мои задачи» не засоряются.
    """
    return sent_at is None or sent_at < now - timedelta(days=TASK_WINDOW_DAYS)


def resolve_folders(folders: Sequence[FolderSetting], mailbox: str) -> tuple[FolderSetting, ...]:
    """Папки опроса: из настройки (без повторов, не больше `MAX_FOLDERS`), иначе одна `mailbox`."""
    seen: set[str] = set()
    out: list[FolderSetting] = []
    for folder in folders:
        name = folder.name.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(FolderSetting(name, folder.spam))
    if not out:
        out.append(FolderSetting(mailbox.strip() or DEFAULT_FOLDER, False))
    return tuple(out[:MAX_FOLDERS])


def primary_folder(folders: Sequence[FolderSetting]) -> str:
    """Главная папка (поле `mailbox` настройки — для совместимости): первая не спам."""
    return next((f.name for f in folders if not f.spam), DEFAULT_FOLDER)


def decode_folder(name: str) -> str:
    """Имя папки IMAP (modified UTF-7, RFC 3501 §5.1.3) → подпись: `&BCEEPwQwBDw-` → «Спам»."""
    out: list[str] = []
    i = 0
    while i < len(name):
        char = name[i]
        if char != "&":
            out.append(char)
            i += 1
            continue
        end = name.find("-", i)
        if end == -1:
            out.append(name[i:])
            break
        chunk = name[i + 1 : end]
        if not chunk:
            out.append("&")
        else:
            padded = chunk.replace(",", "/") + "=" * (-len(chunk) % 4)
            try:
                out.append(base64.b64decode(padded).decode("utf-16-be"))
            except (ValueError, UnicodeDecodeError):
                out.append(name[i : end + 1])
        i = end + 1
    return "".join(out)


def _unquote(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


def parse_list(lines: Sequence[bytes | tuple[bytes, bytes]]) -> list[ServerFolder]:
    """Ответ `LIST "" "*"` → папки. Имя литералом (`{5}`) приходит вторым элементом кортежа."""
    folders: list[ServerFolder] = []
    for item in lines:
        head, literal = (item[0], item[1]) if isinstance(item, tuple) else (item, None)
        match = _LIST_LINE.match(bytes(head).strip())
        if match is None:
            continue
        flags = {f.lower() for f in match.group("flags").decode("ascii", "replace").split()}
        name = _unquote(literal) if literal is not None else _unquote(match.group("name"))
        if not name:
            continue
        folders.append(
            ServerFolder(
                name=name,
                label=decode_folder(name),
                junk="\\junk" in flags,
                selectable="\\noselect" not in flags and "\\nonexistent" not in flags,
            )
        )
    return folders


def suggest_spam(folders: Sequence[ServerFolder]) -> str | None:
    """Спам-папка: по флагу `\\Junk`; флага нет — по единственному привычному имени; иначе нет."""
    flagged = [f.name for f in folders if f.junk and f.selectable]
    if flagged:
        return flagged[0]
    by_name = [
        f.name
        for f in folders
        if f.selectable and f.label.rsplit("/", 1)[-1].strip().lower() in _JUNK_NAMES
    ]
    return by_name[0] if len(by_name) == 1 else None


def pick_history(
    found: Sequence[tuple[FolderSetting, Sequence[int]]], limit: int = HISTORY_LIMIT
) -> tuple[list[tuple[FolderSetting, list[int]]], bool]:
    """Что загрузить: обычные папки раньше спама, в папке — новые раньше (UID по убыванию), всего не
    больше `limit`. Второе значение — упёрлись ли в предел."""
    ordered = sorted(found, key=lambda pair: pair[0].spam)
    left = limit
    out: list[tuple[FolderSetting, list[int]]] = []
    limited = False
    for folder, uids in ordered:
        newest = sorted(set(uids), reverse=True)
        if len(newest) > left:
            limited = True
            newest = newest[:left]
        left -= len(newest)
        if newest:
            out.append((folder, newest))
    return out, limited
