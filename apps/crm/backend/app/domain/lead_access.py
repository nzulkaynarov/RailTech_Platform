"""Объектные правила доступа к лиду, которые решает код (SPEC §1.3). Чистые функции."""

from collections.abc import Iterable
from typing import Final

WORK_ROLES: Final = frozenset({"manager", "admin"})


def may_snooze(*, assigned_user_id: int | None, user_id: int, is_admin: bool) -> bool:
    """«Отложить» передачу (Q-018): без ответственного — любой, кто берёт лидов (общая очередь);
    с ответственным — только он или админ. Право брать лидов проверяет RBAC до вызова."""
    return is_admin or assigned_user_id is None or assigned_user_id == user_id


def may_make_customer(
    *, stage: str, assigned_user_id: int | None, user_id: int, is_admin: bool
) -> bool:
    """«Сделать клиентом»: выигранный лид (или клиент — смена компании); без ответственного —
    любой с правом на клиентов, иначе ответственный или админ. Зеркало — leadActionRules.ts."""
    if stage not in ("won", "customer"):
        return False
    return is_admin or assigned_user_id is None or assigned_user_id == user_id


def may_acknowledge(*, priority: str, status: str) -> bool:
    """«Принято к сведению»: только информационная передача, пока она открыта или отложена.

    Горячие и тёплые передачи ждут человека — их закрывает «Забрать», а не отметка.
    """
    return priority == "info" and status in ("open", "snoozed")


def loses_work_role(before: Iterable[str], after: Iterable[str]) -> bool:
    """Смена ролей лишает права вести лидов: работу передают, как при деактивации."""
    return bool(WORK_ROLES & set(before)) and not WORK_ROLES & set(after)
