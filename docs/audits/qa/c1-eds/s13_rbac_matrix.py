"""Пункт 6: права EDS сотрудников = каталог. /me у каждого; матрица «операция x сотрудник» по x-rt-permissions из eds.yaml:
разрешено ровно то, на что хватает права (проверка прав идёт раньше поиска объекта: нет права -> 403, есть -> 404/422/200 на пустых данных)."""
import re
import uuid

import yaml

from c1lib import *

spec = yaml.safe_load(open("/tmp/c1/eds.yaml"))
ops = []
for path, item in spec["paths"].items():
    for m, op in item.items():
        if m in ("get", "post", "put", "patch", "delete") and "x-rt-permissions" in op:
            ops.append((m.upper(), path, op["x-rt-permissions"], op["operationId"]))
st = load()
EXPECTED = {   # из platform-rbac.yaml (вручную, независимо от кода): шаблоны/системные роли -> коды EDS
    "admin": {"memos.create"},
    "director": {"approvals.decide", "letters.read", "letters.register", "letters.resolve", "memos.approve", "memos.create", "payments.confirm", "registry.export", "registry.read"},
    "mgr_acc": {"letters.read", "memos.create", "payments.confirm", "registry.export", "registry.read"},
    "supply": {"memos.create", "registry.read"},
    "engineer": {"memos.create", "registry.read"},
    "manager": {"letters.read", "memos.create", "registry.read"},
}
bad = 0
for key in ("mgr_acc", "director", "manager", "supply", "engineer", "admin"):
    tk, _ = eds_token(crm_token(st, key))
    c, me, _ = eds("GET", "/api/v1/me", tk)
    got = set(me["permissions"])
    ok = got == EXPECTED[key]
    bad += not ok
    print(f"[{key}] /me: {sorted(got)}  == каталог: {ok}")
    allowed, denied, mism = [], [], []
    for m, p, perms, opid in ops:
        if opid in ("getMe",):
            continue
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), p)
        c, b, _ = eds(m, url, tk, {} if m in ("POST", "PUT", "PATCH") else None)
        exp = (not perms) or bool(set(perms) & got)
        act = c != 403
        (allowed if act else denied).append(opid)
        if exp != act:
            mism.append((opid, c, perms))
    bad += len(mism)
    print(f"   разрешено ({len(allowed)}): {', '.join(allowed)}")
    print(f"   403 ({len(denied)}): {', '.join(denied)}")
    print(f"   расхождений с x-rt-permissions: {mism or 'нет'}")
print("ИТОГ расхождений:", bad)
