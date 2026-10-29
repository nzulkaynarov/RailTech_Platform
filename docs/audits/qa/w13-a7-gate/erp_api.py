#!/usr/bin/env python3
"""Вызов API ERP от имени сотрудника — для действий, у которых в Платформе нет экрана и которые делает не администратор
(например, запрос на новую категорию каталога — его создаёт сотрудник, а решает администратор в Платформе).
Запуск ВНУТРИ сети compose (из контейнера crm-api): адреса — имена сервисов. Только стандартная библиотека Python 3.12.
  QA_EMAIL=… QA_PW=… python erp_api.py METHOD path [json-тело]
Пароль берётся из окружения (его задаёт обёртка из файла состояния вне репозитория), в вывод не попадает."""
import json
import os
import sys
import urllib.error
import urllib.request

CRM = os.environ.get("QA_CRM", "http://crm-api:8000")
ERP = os.environ.get("QA_ERP", "http://erp-backend:8000")


def req(method, url, body=None, token=None):
    h = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw, code = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    try:
        return code, json.loads(raw.decode() or "null")
    except ValueError:
        return code, raw.decode(errors="replace")


def erp_token(email, password):
    c, b = req("POST", CRM + "/api/v1/auth/login", {"email": email, "password": password})
    if c != 200:
        raise SystemExit(f"login: {c}")
    c, b = req("POST", CRM + "/api/v1/auth/sso/token", {"aud": "erp"}, token=b["access_token"])
    if c != 200:
        raise SystemExit(f"sso token: {c} {b}")
    c, b = req("POST", ERP + "/api/v1/auth/sso/exchange/", {"token": b["token"]})
    if c != 200:
        raise SystemExit(f"erp exchange: {c} {b}")
    return b["access_token"]


if __name__ == "__main__":
    method, path = sys.argv[1], sys.argv[2]
    body = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    tok = erp_token(os.environ["QA_EMAIL"], os.environ["QA_PW"])
    code, out = req(method, ERP + "/api/v1/" + path.lstrip("/"), body, tok)
    print(code, json.dumps(out, ensure_ascii=False)[:1500])
