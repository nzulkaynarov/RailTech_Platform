"""Какая эскалация закрывается вместе с запросом клиента (аудит 2026-10-12)."""

import pytest

from app.services.clients import only_service_request


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (["service_request"], True),
        (["service_request", "service_request"], True),
        (["service_request", "attachment_received"], False),
        (["attachment_received"], False),
        ([], False),
        (None, False),
    ],
)
def test_only_service_request(codes: list[str] | None, expected: bool) -> None:
    assert only_service_request(codes) is expected
