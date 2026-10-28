"""Проба Redis без клиентской библиотеки (W15-H8b, B-004): `AUTH`, `PING`, `INFO` по протоколу RESP.

CRM Redis не использует (брокер и кэш — у ERP, Langfuse и Платформы), поэтому зависимость ради
одной пробы не нужна: хватает четырёх команд. Адрес `redis://[:пароль@]хост[:порт][/база]`; пароль
живёт только в запросе `AUTH` и ни в журнал, ни в ошибку не попадает (в `error` — класс
исключения или код ответа).
"""

import asyncio
import contextlib
import time
from dataclasses import dataclass
from urllib.parse import SplitResult, unquote, urlsplit

from app.domain.external_infra import parse_info

TIMEOUT_S = 5.0
MAX_BULK = 1 << 20  # INFO memory и persistence — единицы КБ; больше — не наш ответ


class RespError(Exception):
    """Redis ответил ошибкой (`-ERR …`, `-NOAUTH …`, `-WRONGPASS …`): код — первое слово."""


@dataclass(frozen=True, slots=True)
class RedisProbe:
    error: str | None
    latency_ms: int | None = None
    info: dict[str, str] | None = None


def _command(*args: str) -> bytes:
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        raw = arg.encode()
        out.append(f"${len(raw)}\r\n".encode() + raw + b"\r\n")
    return b"".join(out)


async def _reply(reader: asyncio.StreamReader) -> str:
    line = (await reader.readline()).rstrip(b"\r\n")
    if not line:
        raise ConnectionError("empty reply")
    kind, rest = line[:1], line[1:].decode(errors="replace")
    if kind == b"-":
        raise RespError(rest.split(" ", 1)[0] or "ERR")
    if kind in (b"+", b":"):
        return rest
    if kind == b"$":
        size = int(rest)
        if size < 0:
            return ""
        if size > MAX_BULK:
            raise ConnectionError("reply too large")
        data = await reader.readexactly(size + 2)
        return data[:-2].decode(errors="replace")
    raise ConnectionError("unexpected reply")


async def _ask(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *args: str) -> str:
    writer.write(_command(*args))
    await writer.drain()
    return await _reply(reader)


async def _session(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, parts: SplitResult, started: float
) -> RedisProbe:
    if parts.password:
        login = [unquote(parts.username)] if parts.username else []
        await _ask(reader, writer, "AUTH", *login, unquote(parts.password))
    await _ask(reader, writer, "PING")
    latency = int((time.monotonic() - started) * 1000)
    info = parse_info(await _ask(reader, writer, "INFO", "memory"))
    info |= parse_info(await _ask(reader, writer, "INFO", "persistence"))
    return RedisProbe(None, latency, info)


async def probe(url: str, timeout_s: float = TIMEOUT_S) -> RedisProbe:
    """`PING` и `INFO memory`/`persistence`; сбой — класс ошибки без адреса и пароля."""
    parts = urlsplit(url)
    if not parts.hostname:
        return RedisProbe("BadUrl")
    started = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(parts.hostname, parts.port or 6379), timeout_s
        )
    except (TimeoutError, OSError) as exc:
        return RedisProbe(type(exc).__name__)
    try:
        async with asyncio.timeout(timeout_s):
            return await _session(reader, writer, parts, started)
    except RespError as exc:
        return RedisProbe(f"Redis:{exc}")
    except (TimeoutError, OSError, ConnectionError, ValueError, asyncio.IncompleteReadError) as exc:
        return RedisProbe(type(exc).__name__)
    finally:
        writer.close()
        with contextlib.suppress(OSError, TimeoutError):
            await asyncio.wait_for(writer.wait_closed(), timeout_s)
