#!/usr/bin/env python3
"""Подписчик-заглушка шины rt_bus для замера W13-A0: принимает POST /bus/v1/events и отвечает 200 через DELAY секунд.

Только стандартная библиотека. Подпись HMAC не проверяется (нужна лишь скорость ответа); секрета пары здесь нет.
Журнал — jsonl на stdout: id события, тип, издатель, время приёма (UTC).
Переменные: DELAY (по умолчанию 2.5 с), PORT (9000). `POST /_ctl {"delay": 0.5}` меняет задержку на лету.
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DELAY = float(os.environ.get("DELAY", "2.5"))
PORT = int(os.environ.get("PORT", "9000"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        global DELAY
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        if self.path == "/_ctl":
            DELAY = float(json.loads(raw or b"{}").get("delay", DELAY))
            return self._reply(200, {"delay": DELAY})
        received = time.time()
        try:
            envelope = json.loads(raw)
        except ValueError:
            envelope = {}
        print(
            json.dumps(
                {
                    "ts": time.strftime("%H:%M:%S", time.gmtime(received)) + f".{int(received % 1 * 1000):03d}",
                    "id": envelope.get("id"),
                    "type": envelope.get("type"),
                    "publisher": self.headers.get("X-RT-Publisher"),
                }
            ),
            flush=True,
        )
        time.sleep(DELAY)
        self._reply(200, {"status": "accepted"})

    def do_GET(self) -> None:  # noqa: N802
        self._reply(200, {"status": "ok", "delay": DELAY})

    def log_message(self, *args: object) -> None:  # тихо: журнал — строки выше
        pass


class Server(ThreadingHTTPServer):
    request_queue_size = 512  # всплеск из сотни соединений не должен терять SYN (урок гейта 11c)
    daemon_threads = True


if __name__ == "__main__":
    Server(("0.0.0.0", PORT), Handler).serve_forever()
