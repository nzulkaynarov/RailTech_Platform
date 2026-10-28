"""«Проверить» внешней копии (OPS-GDRIVE-2): разбор ключа, ID папки, ответы Google → причина."""

import json
from typing import Any

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.domain import gdrive
from app.integrations import gdrive as gdrive_api

FOLDER = "0AbCdEfGhIjKlMnOpQrStUvWxYz"
TOKEN_URI = "https://oauth2.googleapis.com/token"
FILES = f"https://www.googleapis.com/drive/v3/files/{FOLDER}"


def _pem() -> tuple[str, Any]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, private.public_key()


PEM, PUBLIC = _pem()


def key_json(**fields: Any) -> str:
    body: dict[str, Any] = {
        "type": "service_account",
        "project_id": "rt-backups",
        "private_key_id": "0123456789abcdef0123456789abcdef1a2b",
        "private_key": PEM,
        "client_email": "rt-offsite-backup@rt-backups.iam.gserviceaccount.com",
        "token_uri": TOKEN_URI,
    }
    body.update(fields)
    return json.dumps(body)


def parsed() -> gdrive.ServiceAccountKey:
    key = gdrive.parse_key(key_json())
    assert isinstance(key, gdrive.ServiceAccountKey)
    return key


def test_parse_key_takes_only_what_is_needed() -> None:
    key = parsed()
    assert key.client_email == "rt-offsite-backup@rt-backups.iam.gserviceaccount.com"
    assert gdrive.key_suffix(key.private_key_id) == "1a2b"
    assert key.token_uri == TOKEN_URI


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        ("не json", "not_json"),
        ("[]", "not_json"),
        (key_json(type="authorized_user"), "not_service_account"),
        (key_json(private_key=""), "missing_fields"),
        (key_json(client_email="nobody"), "missing_fields"),
        ("x" * 20000, "not_json"),
    ],
)
def test_parse_key_rejects_what_is_not_a_service_account_key(raw: str, problem: str) -> None:
    assert gdrive.parse_key(raw) == problem


def test_foreign_token_uri_is_not_trusted() -> None:
    key = gdrive.parse_key(key_json(token_uri="http://evil.example/token"))
    assert isinstance(key, gdrive.ServiceAccountKey)
    assert key.token_uri == TOKEN_URI


@pytest.mark.parametrize(
    ("value", "folder"),
    [
        (FOLDER, FOLDER),
        (f"  {FOLDER}  ", FOLDER),
        (f"https://drive.google.com/drive/folders/{FOLDER}?usp=sharing", FOLDER),
        ("short", None),
        ("../../etc/passwd", None),
        ("", None),
    ],
)
def test_folder_id_or_folder_address(value: str, folder: str | None) -> None:
    assert gdrive.normalize_folder_id(value) == folder


def test_assertion_is_signed_by_the_service_account_key() -> None:
    claims = jwt.decode(
        gdrive_api.assertion(parsed(), now=1_800_000_000),
        PUBLIC,
        algorithms=["RS256"],
        audience=TOKEN_URI,
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["iss"] == "rt-offsite-backup@rt-backups.iam.gserviceaccount.com"
    assert claims["scope"] == "https://www.googleapis.com/auth/drive.readonly"
    assert claims["exp"] - claims["iat"] == 600


def folder_body(**fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": FOLDER,
        "name": "rt-platform-offsite",
        "mimeType": gdrive.FOLDER_MIME,
        "driveId": "0ADriveId",
        "capabilities": {"canAddChildren": True},
    }
    body.update(fields)
    return body


def google_error(status: int, reason: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "errors": [{"reason": reason}]}})


@respx.mock
@pytest.mark.parametrize(
    ("folder", "reason"),
    [
        (httpx.Response(200, json=folder_body()), "ok"),
        (httpx.Response(200, json=folder_body(driveId=None)), "not_shared_drive"),
        (httpx.Response(200, json=folder_body(mimeType="text/plain")), "not_folder"),
        (
            httpx.Response(200, json=folder_body(capabilities={"canAddChildren": False})),
            "read_only",
        ),
        (google_error(404, "notFound"), "folder_not_found"),
        (google_error(403, "accessNotConfigured"), "drive_api_disabled"),
        (google_error(403, "insufficientFilePermissions"), "key_rejected"),
        (google_error(403, "userRateLimitExceeded"), "network"),
        (httpx.Response(503, text="unavailable"), "network"),
    ],
)
async def test_probe_explains_the_folder(folder: httpx.Response, reason: str) -> None:
    token = respx.post(TOKEN_URI).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
    )
    files = respx.get(FILES).mock(return_value=folder)
    result = await gdrive_api.probe(parsed(), FOLDER)
    assert result.reason == reason
    assert token.called
    sent = files.calls.last.request
    assert sent.headers["authorization"] == "Bearer ya29.test"
    assert sent.url.params["supportsAllDrives"] == "true"
    if reason == "ok":
        assert result.folder_name == "rt-platform-offsite"


@respx.mock
async def test_revoked_key_is_rejected_before_drive_is_asked() -> None:
    respx.post(TOKEN_URI).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    files = respx.get(FILES)
    result = await gdrive_api.probe(parsed(), FOLDER)
    assert (result.reason, result.detail) == ("key_rejected", "invalid_grant")
    assert not files.called


@respx.mock
async def test_no_network_is_network_not_a_key_problem() -> None:
    respx.post(TOKEN_URI).mock(side_effect=httpx.ConnectError("down"))
    assert (await gdrive_api.probe(parsed(), FOLDER)).reason == "network"


async def test_broken_private_key_is_rejected_without_network() -> None:
    key = gdrive.parse_key(key_json(private_key="-----BEGIN PRIVATE KEY-----\nnope\n"))
    assert isinstance(key, gdrive.ServiceAccountKey)
    assert (await gdrive_api.probe(key, FOLDER)).reason == "key_rejected"
