#!/usr/bin/env python3
"""Файл состояния для генераторов нагрузки гейта 11c (`qa/w11c-gate/*_gen.py`) на стенде A7: /tmp/w11c/state.json внутри crm-api.
Запуск ВНУТРИ crm-api (после каждого пересоздания контейнера и после смены паролей сотрудников):
  docker exec -e QA_USERS='{"admin":{"email":…,"password":…},"manager":{…},"director":{…}}' rt-c2-crm-api-1 python /tmp/gen_state.py
Пароли — только из окружения вызова (значения живут в файле состояния сценариев вне репозитория); в вывод идут только id сотрудников."""
import json
import os
import urllib.request

CRM = "http://crm-api:8000/api/v1"
users = json.loads(os.environ["QA_USERS"])


def req(method, url, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=30).read())


token = req("POST", CRM + "/auth/login", {"email": users["admin"]["email"], "password": users["admin"]["password"]})["access_token"]
listing = req("GET", CRM + "/users", token=token)
items = listing if isinstance(listing, list) else listing.get("items", listing)
ids = {u["email"]: u["id"] for u in items}
for u in users.values():
    u["id"] = ids[u["email"]]
os.makedirs("/tmp/w11c", exist_ok=True)
json.dump({"users": users}, open("/tmp/w11c/state.json", "w"), ensure_ascii=False)
print({k: u["id"] for k, u in users.items()})
