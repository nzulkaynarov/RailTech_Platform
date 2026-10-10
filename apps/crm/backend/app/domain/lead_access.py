"""Объектные правила доступа к лиду, которые решает код (SPEC §1.3). Чистые функции."""


def may_snooze(*, assigned_user_id: int | None, user_id: int, is_admin: bool) -> bool:
    """«Отложить» передачу (Q-018): без ответственного — любой, кто берёт лидов (общая очередь);
    с ответственным — только он или админ. Право брать лидов проверяет RBAC до вызова."""
    return is_admin or assigned_user_id is None or assigned_user_id == user_id
