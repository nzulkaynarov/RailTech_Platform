#!/usr/bin/env python3
"""Заглушка Telegram Bot API для проверки `crm-bot` на стенде без настоящего токена (S0-4).

Стандартная библиотека, без зависимостей. Бот и API CRM направляются на неё через
`TELEGRAM_API_BASE_URL=http://fake-bot-api:8081`; любой токен формата `<число>:<строка>`
принимается, имя бота — `fakebot<число>` (по нему видно, с каким токеном пришёл вызов).
Токены в журнал не пишутся — только число и последние 4 символа.

Bot API (как у Telegram):  POST /bot<token>/<метод>
  getMe, getUpdates (long polling, ждёт `timeout`), sendMessage (запоминает),
  setWebhook/deleteWebhook/getWebhookInfo; остальные методы профиля и меню — пустой успех.

Управление стендом (без токена):
  POST /_inject   тело — update (JSON): кладёт в очередь getUpdates
  GET  /_log      вызовы Bot API с начала (метод, число токена, параметры)
  POST /_reset    очистить журнал и очередь

Запуск: python3 apps/crm/scripts/fake_bot_api.py [--port 8081]
"""

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl

LOCK = threading.Condition()
UPDATES: list[dict[str, Any]] = []
LOG: list[dict[str, Any]] = []
STATE: dict[str, Any] = {
    "webhook": {"url": "", "secret_set": False},
    "next_message_id": 1,
}

EMPTY_OK: dict[str, Any] = {
    "getMyName": {"name": ""},
    "getMyDescription": {"description": ""},
    "getMyShortDescription": {"short_description": ""},
}
TOKEN_RE = re.compile(r"^/bot(\d+):([^/]+)/(\w+)$")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # тишина в stdout
        return

    def _json(self, status: int, body: Any) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")
        if raw and "json" in ctype:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        if raw and "urlencoded" in ctype:  # aiogram без файлов шлёт форму
            return dict(parse_qsl(raw.decode(errors="replace")))
        if raw:  # с файлами — multipart/form-data
            return {
                m.group(1): m.group(2)
                for m in re.finditer(
                    r'name="(\w+)"\r\n\r\n(.*?)\r\n--',
                    raw.decode(errors="replace"),
                    re.DOTALL,
                )
            }
        return {}

    def do_GET(self) -> None:
        if self.path == "/_log":
            with LOCK:
                self._json(200, LOG)
            return
        self._bot_call()

    def do_POST(self) -> None:
        if self.path == "/_inject":
            update = self._body()
            with LOCK:
                UPDATES.append(update)
                LOCK.notify_all()
            self._json(200, {"queued": len(UPDATES)})
            return
        if self.path == "/_reset":
            with LOCK:
                UPDATES.clear()
                LOG.clear()
            self._json(200, {"ok": True})
            return
        self._bot_call()

    def _bot_call(self) -> None:
        match = TOKEN_RE.match(self.path.split("?")[0])
        if match is None:
            self._json(404, {"ok": False, "description": "Not Found"})
            return
        bot_id, secret, method = match.group(1), match.group(2), match.group(3)
        params = self._body()
        entry = {
            "at": time.strftime("%H:%M:%S"),
            "method": method,
            "bot_id": bot_id,
            "token_tail": secret[-4:],
        }
        if method == "sendMessage":
            entry["chat_id"] = params.get("chat_id")
            entry["text"] = str(params.get("text", ""))[:80]
        if method == "setWebhook":
            STATE["webhook"] = {
                "url": params.get("url", ""),
                "secret_set": bool(params.get("secret_token")),
            }
            entry["url"] = params.get("url", "")
            entry["secret_set"] = bool(params.get("secret_token"))
        if method != "getUpdates":
            with LOCK:
                LOG.append(entry)
        self._json(200, self._result(method, bot_id, params, entry))

    def _result(
        self, method: str, bot_id: str, params: dict[str, Any], entry: dict[str, Any]
    ) -> Any:
        if method == "getMe":
            return {
                "ok": True,
                "result": {
                    "id": int(bot_id),
                    "is_bot": True,
                    "first_name": "Fake",
                    "username": f"fakebot{bot_id}",
                },
            }
        if method == "getUpdates":
            return {"ok": True, "result": self._poll(params)}
        if method == "sendMessage":
            with LOCK:
                message_id = STATE["next_message_id"]
                STATE["next_message_id"] += 1
            chat_id = int(params.get("chat_id") or 0)
            return {
                "ok": True,
                "result": {
                    "message_id": message_id,
                    "date": int(time.time()),
                    "chat": {"id": chat_id, "type": "private"},
                    "text": params.get("text", ""),
                },
            }
        if method == "getWebhookInfo":
            hook = STATE["webhook"]
            return {
                "ok": True,
                "result": {
                    "url": hook["url"],
                    "has_custom_certificate": False,
                    "pending_update_count": len(UPDATES),
                },
            }
        return {"ok": True, "result": EMPTY_OK.get(method, True)}

    def _poll(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        offset = int(params.get("offset") or 0)
        timeout = min(int(params.get("timeout") or 0), 30)
        deadline = time.monotonic() + timeout
        with LOCK:
            while True:
                live = [u for u in UPDATES if int(u.get("update_id", 0)) >= offset]
                UPDATES[:] = live
                if UPDATES or time.monotonic() >= deadline:
                    return list(UPDATES)
                LOCK.wait(timeout=max(0.05, deadline - time.monotonic()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    # Пустой адрес — все интерфейсы (внутри контейнера стенда).
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
