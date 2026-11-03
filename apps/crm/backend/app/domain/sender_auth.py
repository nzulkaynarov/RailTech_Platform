"""Подтверждён ли отправитель письма (MAIL-TYPES): разбор `Authentication-Results` (RFC 8601).

Заголовок ставит почтовый сервер-получатель (MX провайдера: Яндекс 360, Google …); он кладёт его
над всеми заголовками письма. Доверять можно только заголовку, у которого `authserv-id` — наш
сервер (RFC 8601 §5, §7.1): отправитель может написать в письме любой `Authentication-Results` сам.
Берём самый верхний заголовок и смотрим на его id: он среди доверенных — серверов провайдера
нашего ящика (выводятся из хоста IMAP, `PROVIDERS`) или списка, заданного админом в «Почте»;
совпадение по домену с границей по точке — разбираем; чужой или без id — проверить нельзя
(`unknown`). Домен подтверждён, если `dmarc=pass` (DMARC уже требует выравнивания `From`) или
`spf=pass` и `dkim=pass` с выравниванием домена `From` хотя бы по одной подписи.
"""

import re
from collections.abc import Iterable
from typing import Final, Literal

Verdict = Literal["verified", "unverified", "unknown"]

#: Провайдер ящика → чьему `authserv-id` верим. Ключ — суффиксы хоста IMAP настройки «Почта»
#: (`imap.yandex.ru` → `yandex.ru`), значение — суффиксы `authserv-id` его серверов приёма
#: (`mx.yandex.ru`, `mxback12o.mail.yandex.net`). Microsoft 365 часто ставит
#: `Authentication-Results` без `authserv-id` — такое письмо останется «Нельзя проверить»
#: (`unknown`). Хоста нет в таблице — не доверяем никому, пока админ не впишет список сам:
#: заголовок любого другого провайдера в письме может написать кто угодно.
PROVIDERS: Final[tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = (
    (("yandex.ru", "yandex.com"), ("yandex.ru", "yandex.net")),
    (("gmail.com", "googlemail.com"), ("google.com",)),
    (("office365.com",), ("protection.outlook.com",)),
    (("mail.ru",), ("mail.ru",)),
    (("zoho.com", "zoho.eu"), ("zoho.com", "zoho.eu")),
)


def _host(value: str) -> str:
    """Хост из настройки IMAP: без схемы и порта, нижний регистр."""
    host = value.strip().lower().removeprefix("imap://").removeprefix("imaps://")
    return host.split("/", 1)[0].rsplit(":", 1)[0].strip(".")


def provider_trusted(imap_host: str) -> tuple[str, ...]:
    """`authserv-id` провайдера по хосту нашего IMAP; неизвестный хост — пусто."""
    host = _host(imap_host)
    for hosts, servers in PROVIDERS:
        if any(host == h or host.endswith("." + h) for h in hosts):
            return servers
    return ()


def effective_trusted(imap_host: str, explicit: Iterable[str]) -> tuple[str, ...]:
    """Кому верим: список, заданный админом, перекрывает вывод из хоста IMAP."""
    chosen = tuple(x for x in explicit if x.strip())
    return chosen or provider_trusted(imap_host)


_PAIR: Final = re.compile(r"([a-z][a-z0-9_.\-]*)=((?:\"[^\"]*\")|[^\s;]+)", re.IGNORECASE)


def _strip_comments(text: str) -> str:
    """Убрать комментарии RFC 5322 `( … )`, в том числе вложенные; скобки в кавычках не трогать."""
    out: list[str] = []
    depth = 0
    quoted = False
    for char in text:
        if char == '"' and depth == 0:
            quoted = not quoted
        if not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")" and depth > 0:
            depth -= 1
        elif depth == 0:
            out.append(char)
    return "".join(out)


def server_id(header: str) -> str:
    """`authserv-id` заголовка: первое слово до `;` (дальше может идти версия), нижний регистр."""
    head = _strip_comments(header).split(";", 1)[0].split()
    return head[0].strip('"').strip(".").lower() if head else ""


def is_trusted(identifier: str, trusted: Iterable[str]) -> bool:
    """`authserv-id` совпадает с доверенным доменом: он сам или его поддомен (граница по точке)."""
    ident = identifier.lower().strip(".")
    return bool(ident) and any(
        ident == t or ident.endswith("." + t)
        for t in (x.strip().lower().strip(".") for x in trusted)
        if t
    )


def _domain(value: str) -> str:
    """Домен из `user@host`, `@host` или `host`; нижний регистр, без точки в конце."""
    return value.strip().strip('"').rpartition("@")[2].strip().strip(".").lower()


def aligned(left: str, right: str) -> bool:
    """Относительное выравнивание: домены равны или один — поддомен другого (по границе точки)."""
    a, b = _domain(left), _domain(right)
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def _results(header: str) -> list[dict[str, str]]:
    """Части заголовка после `authserv-id;`: метод → результат и свойства (`header.from`,
    `header.d` …).
    """
    parts = _strip_comments(header).split(";")[1:]
    out: list[dict[str, str]] = []
    for part in parts:
        pairs = [(k.lower(), v.strip('"')) for k, v in _PAIR.findall(part)]
        if not pairs:
            continue
        method, result = pairs[0]
        out.append({"method": method, "result": result.lower(), **dict(pairs[1:])})
    return out


def verdict(headers: list[str], from_email: str, trusted: Iterable[str] = ()) -> Verdict:
    """Вердикт по значениям `Authentication-Results` (сверху вниз, как в письме) и адресу `From`.

    Учитывается только самый верхний заголовок и только если его `authserv-id` доверенный."""
    if not headers or "@" not in from_email:
        return "unknown"
    if not is_trusted(server_id(headers[0]), trusted):
        return "unknown"
    found = _results(headers[0])
    if not found:
        return "unknown"
    sender = _domain(from_email)

    def of(method: str) -> list[dict[str, str]]:
        return [r for r in found if r["method"] == method]

    for dmarc in of("dmarc"):
        if dmarc["result"] == "pass" and aligned(dmarc.get("header.from", sender), sender):
            return "verified"
    spf_pass = [r for r in of("spf") if r["result"] == "pass"]
    dkim_pass = [r for r in of("dkim") if r["result"] == "pass"]
    spf_aligned = any(
        aligned(r.get("smtp.mailfrom", r.get("smtp.mail", r.get("smtp.helo", ""))), sender)
        for r in spf_pass
    )
    dkim_aligned = any(aligned(r.get("header.d", r.get("header.i", "")), sender) for r in dkim_pass)
    if spf_pass and dkim_pass and (spf_aligned or dkim_aligned):
        return "verified"
    return "unverified"
