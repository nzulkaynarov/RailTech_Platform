"""Коннектор «Почта» (M3-CRM-08, ADR-0018): чистые правила адреса SMTP и отправителя.

Админ вводит хост релея (`smtp.example.com`), порт и способ шифрования; код не угадывает порт по
способу, но подсказывает типовые (587 — STARTTLS, 465 — SMTPS). Письма уходят только от адреса
отправителя, который задан явно: без него коннектор не настроен.
"""

from typing import Final, Literal

Security = Literal["starttls", "ssl", "none"]
SECURITY_PORTS: Final[dict[Security, int]] = {"starttls": 587, "ssl": 465, "none": 25}
_HOST_CHARS: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")


def normalize_host(raw: str) -> str:
    """Без пробелов, схемы и завершающей точки; в нижнем регистре; пусто — не задан."""
    host = raw.strip().lower()
    for prefix in ("smtp://", "smtps://"):
        host = host.removeprefix(prefix)
    return host.rstrip("/").rstrip(".")


def host_problem(host: str) -> str | None:
    """Почему хост не годится; None — в порядке. Пустой хост — тоже проблема."""
    if not host:
        return "host is missing"
    if len(host) > 253:
        return "host is too long"
    if "://" in host or "/" in host or ":" in host:
        return "host must not contain scheme, path or port"
    if any(ch not in _HOST_CHARS for ch in host):
        return "host contains invalid characters"
    if any(not label or len(label) > 63 for label in host.split(".")):
        return "host has an empty or too long label"
    return None


def email_problem(address: str) -> str | None:
    """Грубая проверка адреса отправителя: один `@`, непустые части, без пробелов."""
    value = address.strip()
    if not value:
        return "address is missing"
    if " " in value or value.count("@") != 1:
        return "address is malformed"
    local, _, domain = value.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return "address is malformed"
    return None


def format_sender(from_email: str, from_name: str) -> str:
    """`Имя <адрес>` для заголовка `From`; без имени — просто адрес."""
    name = from_name.strip().replace('"', "")
    return f'"{name}" <{from_email}>' if name else from_email
