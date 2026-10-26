"""Общие функции скриптов гейта C1 (E6). Только стандартная библиотека Python 3.12.

Скрипты запускаются ВНУТРИ сети compose стенда `rt-c1` (из контейнера `crm-api`: он не останавливается в ходе гейта),
потому что у EDS нет внешнего маршрута. Адреса — имена сервисов compose. Пароли и токены демо-сотрудников генерируются
на лету и лежат только в файле состояния внутри контейнера (STATE), в репозиторий и отчёт не попадают.
"""
import json
import os
import secrets
import time
import urllib.error
import urllib.request

CRM = os.environ.get("C1_CRM", "http://crm-api:8000")
ERP = os.environ.get("C1_ERP", "http://erp-backend:8000")
EDS = os.environ.get("C1_EDS", "http://eds-api:8000")
STATE = os.environ.get("C1_STATE", "/tmp/c1/state.json")


def req(method, url, body=None, token=None, headers=None, timeout=30):
    """HTTP-вызов; возвращает (статус, разобранный JSON или текст, заголовки)."""
    data = None
    h = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw, code, hdrs = resp.read(), resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw, code, hdrs = e.read(), e.code, dict(e.headers)
    except Exception as e:  # сеть/таймаут
        return 0, {"error": repr(e)}, {}
    try:
        return code, json.loads(raw.decode() or "null"), hdrs
    except ValueError:
        return code, raw.decode(errors="replace"), hdrs


def load():
    try:
        return json.load(open(STATE))
    except FileNotFoundError:
        return {}


def save(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w"), ensure_ascii=False, indent=1)


def newpw():
    return "Gate-" + secrets.token_hex(8) + "-Aa1"


def crm_login(email, password):
    c, b, _ = req("POST", CRM + "/api/v1/auth/login", {"email": email, "password": password})
    if c != 200:
        raise RuntimeError(f"login {email}: {c} {b}")
    return b["access_token"]


def crm_token(st, key):
    """Токен доступа CRM сотрудника из состояния (вход по сохранённому паролю)."""
    u = st["users"][key]
    return crm_login(u["email"], u["password"])


def eds_token(crm_access):
    """CRM SSO-токен (aud=eds) -> обмен в EDS -> Bearer. Возвращает (токен, подробности)."""
    c, b, _ = req("POST", CRM + "/api/v1/auth/sso/token", {"aud": "eds"}, token=crm_access)
    if c != 200:
        return None, {"stage": "crm_sso_token", "status": c, "body": b}
    c2, b2, _ = req("POST", EDS + "/api/v1/auth/sso/exchange", {"token": b["token"]})
    if c2 != 200:
        return None, {"stage": "eds_exchange", "status": c2, "body": b2}
    return b2["access_token"], {"expires_in": b2.get("expires_in")}


def eds(method, path, token, body=None, headers=None):
    return req(method, EDS + path, body, token=token, headers=headers)


def wait(cond, timeout=120, step=1.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = cond()
        if v:
            return v
        time.sleep(step)
    return None


def pj(x):
    print(json.dumps(x, ensure_ascii=False, indent=1, default=str))


def erp_token(crm_access):
    """CRM SSO-токен (aud=erp) -> обмен в ERP -> токен доступа ERP."""
    c, b, _ = req("POST", CRM + "/api/v1/auth/sso/token", {"aud": "erp"}, token=crm_access)
    if c != 200:
        return None
    c2, b2, _ = req("POST", ERP + "/api/v1/auth/sso/exchange/", {"token": b["token"]})
    return b2.get("access_token") if c2 == 200 else None
