"""Подтверждён ли отправитель письма (MAIL-TYPES): разбор `Authentication-Results` (RFC 8601).

Заголовок ставит почтовый сервер-получатель (MX провайдера: Яндекс 360, Google), самое верхнее
значение — его. По нему, а не по `From`, можно доверять правилу «домен → тип»: `From` подделывается
как угодно, SPF/DKIM/DMARC — нет. Домен подтверждён, если `dmarc=pass` (DMARC уже требует
выравнивания `From`) или `spf=pass` и `dkim=pass` с выравниванием домена `From` хотя бы по одной
подписи. Заголовка нет вовсе — проверить нельзя (`unknown`).

"""

import re
from typing import Final, Literal

Verdict = Literal["verified", "unverified", "unknown"]

_PAIR: Final = re.compile(r"([a-z][a-z0-9_.\-]*)=((?:\"[^\"]*\")|[^\s;]+)", re.IGNORECASE)
_COMMENT: Final = re.compile(r"\([^)]*\)")


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
    parts = _COMMENT.sub(" ", header).split(";")[1:]
    out: list[dict[str, str]] = []
    for part in parts:
        pairs = [(k.lower(), v.strip('"')) for k, v in _PAIR.findall(part)]
        if not pairs:
            continue
        method, result = pairs[0]
        out.append({"method": method, "result": result.lower(), **dict(pairs[1:])})
    return out


def verdict(headers: list[str], from_email: str) -> Verdict:
    """Вердикт по значениям `Authentication-Results` (сверху вниз, как в письме) и адресу `From`."""
    if not headers or "@" not in from_email:
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
        aligned(r.get("smtp.mailfrom", r.get("smtp.helo", "")), sender) for r in spf_pass
    )
    dkim_aligned = any(aligned(r.get("header.d", r.get("header.i", "")), sender) for r in dkim_pass)
    if spf_pass and dkim_pass and (spf_aligned or dkim_aligned):
        return "verified"
    return "unverified"
