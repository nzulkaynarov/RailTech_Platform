"""«Сделать клиентом», «Принято к сведению», потеря рабочей роли (аудит 2026-10-12)."""

import pytest

from app.domain.lead_access import loses_work_role, may_acknowledge, may_make_customer

ME, OTHER = 1, 2


@pytest.mark.parametrize(
    ("stage", "assigned", "is_admin", "allowed"),
    [
        ("won", None, False, True),
        ("won", ME, False, True),
        ("won", OTHER, False, False),  # чужой выигранный лид — только ответственный или админ
        ("won", OTHER, True, True),
        ("customer", ME, False, True),
        ("in_progress", ME, False, False),
        ("lost", None, True, False),
    ],
)
def test_may_make_customer(stage: str, assigned: int | None, is_admin: bool, allowed: bool) -> None:
    got = may_make_customer(stage=stage, assigned_user_id=assigned, user_id=ME, is_admin=is_admin)
    assert got is allowed


def test_may_make_customer_erp_mode() -> None:
    from app.domain.backoffice import BackofficeMode

    # В ERP режиме in_progress разрешен для ответственного или админа
    assert may_make_customer(
        stage="in_progress",
        assigned_user_id=ME,
        user_id=ME,
        is_admin=False,
        mode=BackofficeMode.ERP,
    )
    assert not may_make_customer(
        stage="in_progress",
        assigned_user_id=OTHER,
        user_id=ME,
        is_admin=False,
        mode=BackofficeMode.ERP,
    )
    assert may_make_customer(
        stage="in_progress",
        assigned_user_id=OTHER,
        user_id=ME,
        is_admin=True,
        mode=BackofficeMode.ERP,
    )


@pytest.mark.parametrize(
    ("priority", "status", "allowed"),
    [
        ("info", "open", True),
        ("info", "snoozed", True),
        ("info", "taken", False),
        ("info", "closed", False),
        ("warm", "open", False),
        ("hot", "open", False),
    ],
)
def test_may_acknowledge(priority: str, status: str, allowed: bool) -> None:
    assert may_acknowledge(priority=priority, status=status) is allowed


@pytest.mark.parametrize(
    ("before", "after", "loses"),
    [
        (["manager"], ["viewer"], True),
        (["admin"], ["viewer"], True),
        (["admin", "manager"], ["manager"], False),
        (["manager"], ["admin"], False),
        (["viewer"], ["viewer"], False),
    ],
)
def test_loses_work_role(before: list[str], after: list[str], loses: bool) -> None:
    assert loses_work_role(before, after) is loses
