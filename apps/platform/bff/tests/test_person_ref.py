"""СУЩ-3: «кто сделал» из ERP — `PersonRef` с id сотрудника CRM; старая ERP без ссылки — имя без id."""

import pytest

from app.feeds.models import PersonRef
from app.schemas_person import person_of


def test_ref_with_crm_id() -> None:
    assert person_of({"crm_user_id": 7, "name": "Иван Тестов"}, "Иван Тестов") == PersonRef(
        id="7", name="Иван Тестов", initials="ИТ"
    )


def test_old_erp_gives_the_name_only() -> None:
    assert person_of(None, "Демо") == PersonRef(id="", name="Демо", initials="Д")


@pytest.mark.parametrize(
    ("ref", "name"),
    [(None, None), (None, " "), ({"crm_user_id": 7, "name": ""}, None), ("Иван", None)],
)
def test_nobody_is_none(ref: object, name: object) -> None:
    assert person_of(ref, name) is None


def test_link_without_crm_user_keeps_the_name() -> None:
    assert person_of({"crm_user_id": None, "name": "Системный"}).id == ""  # type: ignore[union-attr]
