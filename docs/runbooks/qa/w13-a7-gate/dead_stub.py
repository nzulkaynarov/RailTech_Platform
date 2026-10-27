#!/usr/bin/env python3
"""Подписчик-заглушка шины rt_bus для гейта C2a: на любой POST /bus/v1/events отвечает 400 (неповторяемая ошибка, доставка сразу
уходит в dead/DLQ — rt-bus.md §5). Только стандартная библиотека. Журнал — jsonl на stdout (id, тип события, издатель). Секретов нет:
подпись не проверяется. Переменная CODE меняет статус ответа (по умолчанию 400)."""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CODE = int(os.environ.get("CODE", "400"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        try:
            env = json.loads(raw)
        except ValueError:
            env = {}
        print(json.dumps({"ts": time.strftime("%H:%M:%S"), "id": env.get("id"), "type": env.get("type"),
                          "publisher": self.headers.get("X-RT-Publisher"), "answered": CODE}), flush=True)
        body = json.dumps({"error": "qa-dead-stub"}).encode()
        self.send_response(CODE)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
