"""Сотрудник «кто сделал» из ответа домена (план СУЩ-3): `PersonRef` с id сотрудника CRM.

ERP отдаёт рядом с прежним именем ссылку `{crm_user_id, name}`; по id Платформа берёт фото и
должность из справочника сотрудников. Нет ссылки (старая ERP) — имя без id; нет имени — `None`.
"""

from typing import Any

from app.feeds.models import PersonRef
from app.schemas import initials_of


def person_of(ref: Any, name: Any = None) -> PersonRef | None:
    if isinstance(ref, dict) and isinstance(ref.get("name"), str) and ref["name"].strip():
        crm = ref.get("crm_user_id")
        pid = str(crm) if isinstance(crm, int) and not isinstance(crm, bool) and crm > 0 else ""
        text = ref["name"].strip()
    elif isinstance(name, str) and name.strip():
        pid, text = "", name.strip()
    else:
        return None
    return PersonRef(id=pid, name=text, initials=initials_of(text, ""))
