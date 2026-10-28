"""Проба Redis по протоколу RESP против подставного сервера (W15-H8b, B-004): без Redis и сети."""

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest

from app.integrations.redis_probe import probe

PASSWORD = "fake-test-password"  # фиктивный, только для подставного сервера
INFO_MEMORY = "# Memory\r\nused_memory:1048576\r\nmaxmemory:2097152\r\n"
INFO_PERSISTENCE = "# Persistence\r\nrdb_last_save_time:1793170000\r\naof_last_write_status:ok\r\n"


def bulk(text: str) -> bytes:
    raw = text.encode()
    return b"$%d\r\n%s\r\n" % (len(raw), raw)


class Server:
    """Минимальный Redis: что спросили — в `commands`, ответы — по таблице."""

    def __init__(self, password: str | None = None) -> None:
        self.password = password
        self.commands: list[list[str]] = []
        self.authed = password is None

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while header := await reader.readline():
                count = int(header[1:])
                args: list[str] = []
                for _ in range(count):
                    size = int((await reader.readline())[1:])
                    args.append((await reader.readexactly(size + 2))[:-2].decode())
                self.commands.append(args)
                writer.write(self.answer(args))
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    def answer(self, args: list[str]) -> bytes:
        name = args[0].upper()
        if name == "AUTH":
            if args[-1] == self.password:
                self.authed = True
                return b"+OK\r\n"
            return b"-WRONGPASS invalid username-password pair\r\n"
        if not self.authed:
            return b"-NOAUTH Authentication required.\r\n"
        if name == "PING":
            return b"+PONG\r\n"
        if name == "INFO":
            return bulk(INFO_MEMORY if args[1] == "memory" else INFO_PERSISTENCE)
        return b"-ERR unknown command\r\n"


@pytest.fixture
async def serve() -> AsyncIterator[Callable[[Server], asyncio.Future[int]]]:
    servers: list[asyncio.Server] = []

    async def start(server: Server) -> int:
        started = await asyncio.start_server(server.handle, "127.0.0.1", 0)
        servers.append(started)
        return int(started.sockets[0].getsockname()[1])

    yield start  # type: ignore[misc]
    for started in servers:
        started.close()
        await started.wait_closed()


async def test_probe_reads_memory_and_persistence(
    serve: Callable[[Server], asyncio.Future[int]],
) -> None:
    server = Server(PASSWORD)
    port = await serve(server)
    result = await probe(f"redis://:{PASSWORD}@127.0.0.1:{port}/0")
    assert result.error is None
    assert result.info == {
        "used_memory": "1048576",
        "maxmemory": "2097152",
        "rdb_last_save_time": "1793170000",
        "aof_last_write_status": "ok",
    }
    assert result.latency_ms is not None
    assert [c[0] for c in server.commands] == ["AUTH", "PING", "INFO", "INFO"]


async def test_probe_without_a_password_skips_auth(
    serve: Callable[[Server], asyncio.Future[int]],
) -> None:
    server = Server()
    result = await probe(f"redis://127.0.0.1:{await serve(server)}")
    assert result.error is None
    assert server.commands[0] == ["PING"]


@pytest.mark.parametrize(
    ("url_password", "error"), [("wrong", "Redis:WRONGPASS"), (None, "Redis:NOAUTH")]
)
async def test_probe_reports_the_redis_error_code_without_the_password(
    serve: Callable[[Server], asyncio.Future[int]], url_password: str | None, error: str
) -> None:
    port = await serve(Server(PASSWORD))
    auth = f":{url_password}@" if url_password else ""
    result = await probe(f"redis://{auth}127.0.0.1:{port}")
    assert result.error == error
    assert result.info is None
    assert "wrong" not in (result.error or "")


async def test_probe_connection_refused_and_bad_url() -> None:
    free = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = int(free.sockets[0].getsockname()[1])
    free.close()
    await free.wait_closed()
    assert (await probe(f"redis://:x@127.0.0.1:{port}")).error == "ConnectionRefusedError"
    assert (await probe("not a url")).error == "BadUrl"


async def test_probe_gives_up_on_a_silent_server() -> None:
    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(5)

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    try:
        result = await probe(f"redis://127.0.0.1:{port}", timeout_s=0.3)
    finally:
        server.close()
    assert result.error == "TimeoutError"
