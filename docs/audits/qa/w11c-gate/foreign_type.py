"""Пункт 5: отказ по домену типа (400 foreign_type). Ручные подписанные запросы секретами пар из окружения crm-api (значения не печатаются)."""
import json, os, urllib.request, urllib.error, uuid
from datetime import datetime, timezone
from rt_bus.signing import signed_headers

D = os.path.dirname(os.path.abspath(__file__))
def tmpl(name): return json.load(open(f"{D}/{name}"))
def send(url, publisher, secret_env, env, mutate=None, bad_sig=False):
    e = dict(env); e["id"] = str(uuid.uuid4())
    if mutate: mutate(e)
    body = json.dumps(e, ensure_ascii=False).encode()
    secret = os.environ[secret_env] if not bad_sig else "wrong-secret"
    h = signed_headers(publisher=publisher, event_id=e["id"], body=body, secret=secret, now=datetime.now(timezone.utc), correlation_id=e.get("correlationid"))
    r = urllib.request.Request(url, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp: return resp.status, resp.read().decode()[:120]
    except urllib.error.HTTPError as ex: return ex.code, ex.read().decode()[:120]

def as_type(t, src):
    def m(e): e["type"] = t; e["source"] = src; e["dataschema"] = "rt://contracts/events/" + t.split(".")[2] + "/" + ".".join(t.split(".")[3:5]) + "/v1"
    return m
EDS = "http://eds-api:8000/bus/v1/events"; BFF = "http://platform-bff:8000/bus/v1/events"; CRM = "http://crm-api:8000/bus/v1/events"
ident, erp, crmc = tmpl("env_identity.json"), tmpl("env_erp.json"), tmpl("env_crm_client.json")
cases = [
 ("crm -> eds: identity.user.created (домен identity принадлежит crm)", EDS, "crm", "RT_BUS_SECRET_CRM_EDS", ident, None, 200),
 ("crm -> eds: erp.deal.stage_changed от имени crm (source rt://crm)", EDS, "crm", "RT_BUS_SECRET_CRM_EDS", erp, as_type("uz.railtech.erp.deal.stage_changed.v1", "rt://crm"), 400),
 ("crm -> eds: eds.letter.registered от имени crm", EDS, "crm", "RT_BUS_SECRET_CRM_EDS", erp, as_type("uz.railtech.eds.letter.registered.v1", "rt://crm"), 400),
 ("crm -> platform-bff: identity.user.created", BFF, "crm", "RT_BUS_SECRET_CRM_PLATFORM_BFF", ident, None, 200),
 ("crm -> platform-bff: erp.deal.stage_changed от имени crm", BFF, "crm", "RT_BUS_SECRET_CRM_PLATFORM_BFF", erp, as_type("uz.railtech.erp.deal.stage_changed.v1", "rt://crm"), 400),
 ("crm -> platform-bff: crm.client.updated (свой домен crm)", BFF, "crm", "RT_BUS_SECRET_CRM_PLATFORM_BFF", crmc, None, 200),
 ("erp -> crm: erp.deal.stage_changed (свой домен)", CRM, "erp", "RT_BUS_SECRET_ERP_CRM", erp, None, 200),
 ("erp -> crm: crm.client.updated от имени erp (source rt://erp)", CRM, "erp", "RT_BUS_SECRET_ERP_CRM", crmc, as_type("uz.railtech.crm.client.updated.v1", "rt://erp"), 400),
 ("erp -> crm: identity.user.created от имени erp", CRM, "erp", "RT_BUS_SECRET_ERP_CRM", ident, as_type("uz.railtech.identity.user.created.v1", "rt://erp"), 400),
]
for title, url, pub, sec, env, mut, want in cases:
    code, txt = send(url, pub, sec, env, mut)
    print(("OK " if code == want else "!! "), f"{code} (ожидалось {want})", title, "|", txt)
code, txt = send(EDS, "crm", "RT_BUS_SECRET_CRM_EDS", erp, as_type("uz.railtech.erp.deal.stage_changed.v1", "rt://crm"), bad_sig=True)
print("OK " if code == 401 else "!! ", f"{code} (ожидалось 401)", "контроль: чужой тип с неверной подписью -> подпись проверяется раньше домена |", txt)
