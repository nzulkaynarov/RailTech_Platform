"""Типы входящих писем общего ящика как данные (MAIL-TYPES): справочник, правила отправителя, разбор
ответа ИИ.

Чистые функции без I/O (CONVENTIONS.md §4). Типы — данные администратора (название ru/uz/en, цвет
и значок из
закрытого набора, порядок, «действует»); **поведение — код из закрытого списка действий**
(`ACTIONS`): что делает
основная кнопка карточки, решает код, а не модель и не текст справочника. Эталоны: Front (rules +
tags), Gmail
(filters + categories), Help Scout (workflows), Zendesk (triggers) — «отправитель или домен → тип»
применяется до
ИИ и побеждает его; ИИ только предлагает тип из действующих, человек подтверждает кнопкой или
меняет одним щелчком.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

Action = Literal[
    "register_incoming",
    "create_lead",
    "supplier_price",
    "to_accountant",
    "archive_mailing",
    "reply_template",
    "suspicious",
]
TypeSource = Literal["rule", "ai", "manual"]

KIND: Final = "mail-types"
# : Закрытый список действий по умолчанию: добавить действие — значит написать код, не строку
# справочника.
ACTIONS: Final[tuple[Action, ...]] = (
    "register_incoming",
    "create_lead",
    "supplier_price",
    "to_accountant",
    "archive_mailing",
    "reply_template",
    "suspicious",
)
#: Цвет тега — тона интерфейса (`StatusTone`); значок — имя из набора Платформы.
COLORS: Final[tuple[str, ...]] = ("blue", "green", "gold", "red", "purple", "cyan", "default")
ICONS: Final[tuple[str, ...]] = (
    "mail",
    "team",
    "calendar",
    "file",
    "wallet",
    "bank",
    "notification",
    "stop",
)
SOURCES: Final[tuple[str, ...]] = ("rule", "ai", "manual")
CODE_PATTERN: Final = r"^[a-z][a-z_]{0,31}$"
POSITION_STEP: Final = 10
# : Сколько типов показываем модели: промпт не растёт без предела, админ видит предупреждение в
# справке.
MAX_PROMPT_TYPES: Final = 30


@dataclass(frozen=True, slots=True)
class SeedType:
    code: str
    ru: str
    uz: str
    en: str
    color: str
    icon: str
    action: Action
    #: Вид документа EDS (код `letter-kinds`) для предзаполнения формы ВХ; нет такого — не трогаем.
    letter_kind: str | None = None


# : Стартовый набор: администратор может переименовать, поменять действие, отключить; удалить
# использованное нельзя.
SEED: Final[tuple[SeedType, ...]] = (
    SeedType(
        "client_request",
        "Запрос клиента",
        "Mijoz so'rovi",
        "Customer request",
        "green",
        "mail",
        "create_lead",
    ),
    SeedType(
        "cooperation",
        "Предложение о сотрудничестве",
        "Hamkorlik taklifi",
        "Partnership offer",
        "purple",
        "team",
        "register_incoming",
    ),
    SeedType(
        "meeting",
        "Приглашение на встречу",
        "Uchrashuvga taklif",
        "Meeting invitation",
        "cyan",
        "calendar",
        "reply_template",
    ),
    SeedType(
        "supplier_price",
        "КП или прайс поставщика",
        "Yetkazib beruvchi narxnomasi",
        "Supplier quote or price list",
        "blue",
        "file",
        "supplier_price",
    ),
    SeedType(
        "supplier_invoice",
        "Счёт поставщика",
        "Yetkazib beruvchi hisobi",
        "Supplier invoice",
        "gold",
        "wallet",
        "to_accountant",
    ),
    SeedType(
        "supplier_document",
        "Документ поставщика (договор, акт сверки)",
        "Yetkazib beruvchi hujjati (shartnoma, solishtirma dalolatnoma)",
        "Supplier document (contract, reconciliation act)",
        "blue",
        "file",
        "register_incoming",
        "supplier",
    ),
    SeedType(
        "official",
        "Официальное письмо (госорган, банк, налоговая)",
        "Rasmiy xat (davlat organi, bank, soliq)",
        "Official letter (authority, bank, tax)",
        "red",
        "bank",
        "register_incoming",
        "government",
    ),
    SeedType(
        "mailing",
        "Рассылка",
        "Reklama xabarnomasi",
        "Newsletter",
        "default",
        "notification",
        "archive_mailing",
    ),
    SeedType("spam", "Спам", "Spam", "Spam", "default", "stop", "suspicious"),
)

# --- правила «отправитель или домен → тип»
# ---------------------------------------------------------------------

_DOMAIN: Final = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_EMAIL: Final = re.compile(r"^[^@\s<>,;]{1,64}@([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


def normalize_pattern(raw: str) -> str | None:
    """Правило отправителя → одна нормальная форма: адрес `ivan@firma.uz` или домен `firma.uz`.

    Принимаем то, что админ привык писать в фильтре почты: `*@soliq.uz`, `@soliq.uz`, `soliq.uz`,
    адрес целиком.
    Что не адрес и не домен — `None`.
    """
    text = raw.strip().lower()
    if text.startswith("*@"):
        text = text[2:]
    elif text.startswith("@"):
        text = text[1:]
    if _EMAIL.match(text):
        return text
    return text if _DOMAIN.match(text) else None


def pattern_domain(pattern: str) -> str:
    return pattern.rpartition("@")[2]


def _matches(pattern: str, sender: str) -> int:
    """Насколько точно правило подходит отправителю: 0 — не подходит, больше — точнее.

    Адрес целиком — самый точный; домен подходит и к своим поддоменам (`mail.soliq.uz` для
    `soliq.uz`), чем длиннее
    домен правила, тем оно точнее. Граница — по точке, чужой домен с тем же окончанием не подходит.
    """
    if "@" in pattern:
        return 10_000 if pattern == sender else 0
    domain = sender.rpartition("@")[2]
    if domain == pattern or domain.endswith("." + pattern):
        return len(pattern)
    return 0


def best_rule[T](sender: str, rules: Iterable[tuple[str, T]]) -> T | None:
    """Правило, которое побеждает для отправителя: адрес целиком точнее домена, длинный домен точнее
    короткого.

    Среди равных по точности выигрывает первое в порядке `rules` (вызывающий отдаёт их по
    возрасту)."""
    low = sender.strip().lower()
    if "@" not in low:
        return None
    best: tuple[int, T] | None = None
    for pattern, value in rules:
        score = _matches(pattern, low)
        if score and (best is None or score > best[0]):
            best = (score, value)
    return best[1] if best else None


# --- ответ ИИ -----------------------------------------------------------------------------------
# ----------------


@dataclass(frozen=True, slots=True)
class ActiveType:
    """Действующий тип, как его видит модель: код и названия на трёх языках."""

    code: str
    names: tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class TypeVerdict:
    """Ответ модели после проверки кодом: тип — только из действующих (иначе `None`), суть — своими
    словами."""

    type_code: str | None
    summary: str


SUMMARY_MAX_CHARS: Final = 300
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
_FENCE: Final = re.compile(r"```[a-zA-Z]*\s*(.*?)```", re.DOTALL)
_SEP: Final = re.compile(r"[\s\-]+")


def types_block(types: Sequence[ActiveType]) -> str:
    """Список типов для промпта: данные справочника, не текст в коде. Названия модель видит на
    русском."""
    return "\n".join(f"- `{t.code}` — {t.names[0]}" for t in types[:MAX_PROMPT_TYPES])


def _first_object(raw: str) -> tuple[dict[str, object] | None, str | None]:
    fenced = _FENCE.search(raw)
    text = fenced.group(1) if fenced else raw
    decoder = json.JSONDecoder()
    seen_json = False
    for start, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        seen_json = True
        if isinstance(value, dict):
            return value, None
    return None, "no_object" if seen_json else "not_json"


def _key(value: str) -> str:
    return _SEP.sub("_", value.strip().strip(".«»\"'`").lower())


def pick_type(value: object, types: Iterable[ActiveType]) -> str | None:
    """Код типа из ответа модели: точный код действующего типа или его название (любой из трёх
    языков).

    Всё остальное — выдумка модели или отключённый тип: `None`. Синонимов в коде нет — список
    типов данные."""
    if not isinstance(value, str):
        return None
    wanted = _key(value)
    if not wanted:
        return None
    for item in types:
        if wanted == _key(item.code) or wanted in {_key(n) for n in item.names if n}:
            return item.code
    return None


def parse_verdict(
    raw: str | None, types: Sequence[ActiveType]
) -> tuple[TypeVerdict | None, str | None]:
    """Ответ модели `{"type": …, "summary": …}` → вердикт или причина отказа словом-кодом (в лог,
    без
    текста письма).

    Неизвестный или отключённый тип при понятной сути — вердикт с пустым типом (человек выберет
    сам); нет ни типа,
    ни сути — отказ (`not_json`, `no_object`, `empty_summary`).
    """
    data, problem = _first_object(raw or "")
    if data is None:
        return None, problem
    summary = data.get("summary")
    text = ""
    if isinstance(summary, str):
        text = _CONTROL.sub(" ", summary).strip()[:SUMMARY_MAX_CHARS].strip()
    chosen = pick_type(data.get("type"), types[:MAX_PROMPT_TYPES])
    if not text:
        return None, "empty_summary"
    return TypeVerdict(chosen, text), (None if chosen else "unknown_type")


def action_of(types: Mapping[str, Action], code: str | None) -> Action | None:
    return types.get(code) if code else None


_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "ў": "o",
        "қ": "q",
        "ғ": "g",
        "ҳ": "h",
    }
)


def slug(name: str) -> str:
    """Код из названия: латиница и `_`, начинается с буквы, до 28 знаков (запас под суффикс
    уникальности)."""
    text = re.sub(r"[^a-z]+", "_", name.lower().translate(_TRANSLIT)).strip("_")
    text = text[:28].rstrip("_")
    return text if text else "item"


#: Публичные почтовые сервисы: правило на такой домен ловит кого угодно — админу предупреждение.
PUBLIC_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "mail.ru",
        "inbox.ru",
        "list.ru",
        "bk.ru",
        "internet.ru",
        "yandex.ru",
        "yandex.com",
        "ya.ru",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "icloud.com",
        "me.com",
        "rambler.ru",
        "proton.me",
        "protonmail.com",
        "aol.com",
        "gmx.com",
        "zoho.com",
        "mail.com",
        "bk.uz",
        "inbox.uz",
        "umail.uz",
        "mail.uz",
    }
)


def is_public_domain(pattern: str) -> bool:
    """Шаблон правила — публичный почтовый сервис (домен или адрес на нём)."""
    domain = pattern.rpartition("@")[2]
    return domain in PUBLIC_DOMAINS or any(domain.endswith("." + d) for d in PUBLIC_DOMAINS)


def pattern_matches(pattern: str, sender: str) -> bool:
    """Подходит ли отправитель под шаблон правила (адрес целиком или домен с поддоменами)."""
    return best_rule(sender, [(pattern, True)]) is True
