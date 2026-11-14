"""Plan 0.4 (FR-9): «Создать заявку» needs a basis — the letter or request file uploaded to EDS."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.client_requests import RequestCreate

BODY = {
    "request_key": str(uuid.uuid4()),
    "company": {"name": "ООО Пример", "inn": "301234567"},
    "contact": {"full_name": "Алишер Каримов", "phone": "+998901234567"},
    "summary": "20 комплектов",
}


@pytest.mark.parametrize("letter", [None, ""])
def test_request_without_a_basis_is_refused(letter: object) -> None:
    body = dict(BODY) if letter is None else {**BODY, "letter_file_id": letter}
    with pytest.raises(ValidationError) as caught:
        RequestCreate.model_validate(body)
    assert any(error["loc"] == ("letter_file_id",) for error in caught.value.errors())


def test_request_with_a_basis_is_accepted() -> None:
    letter = uuid.uuid4()
    assert (
        RequestCreate.model_validate({**BODY, "letter_file_id": str(letter)}).letter_file_id
        == letter
    )
