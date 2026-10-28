"""Файлы (pg, S3 заменён памятью): загрузка, версии, привязка, видимость, типы и размер, потоковое чтение."""

import hashlib
from typing import Any

import httpx
import pytest

from app.container import Container
from app.services import files as files_service
from app.services.storage import CHUNK, TEST_STORAGE
from tests.domain import Person, validate
from tests.test_api_auth import assert_error
from tests.test_documents import MEMO, create, submit
from tests.test_letters import NEW_LETTER

pytestmark = pytest.mark.pg

PDF = b"%PDF-1.7\n" + b"x" * 1000
PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 100
DOCX = b"PK\x03\x04" + b"z" * 100
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def upload(
    client: httpx.AsyncClient,
    who: Person,
    content: bytes = PDF,
    *,
    name: str = "счёт.pdf",
    content_type: str = "application/pdf",
    version_of: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        "/api/v1/files",
        files={"file": (name, content, content_type)},
        data={"version_of": version_of} if version_of else None,
        headers={**who.headers, **(headers or {})},
    )


async def test_upload_returns_ref_stores_object_and_streams_it_back(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    response = await upload(client, staff["manager"])
    assert response.status_code == 201, response.text
    ref: dict[str, Any] = response.json()
    validate("FileRef", ref)
    assert (ref["name"], ref["content_type"], ref["size"], ref["version"]) == (
        "счёт.pdf",
        "application/pdf",
        len(PDF),
        1,
    )
    assert ref["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert ref["uploaded_by"] == {"crm_user_id": 5, "full_name": "Алия Каримова"}
    assert TEST_STORAGE.objects[f"files/{ref['id']}/v1"] == (PDF, "application/pdf")

    got = await client.get(f"/api/v1/files/{ref['id']}", headers=staff["manager"].headers)
    assert got.status_code == 200 and got.content == PDF
    assert got.headers["content-type"] == "application/pdf"
    assert got.headers["etag"] == f'"{ref["sha256"]}"'
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert "%D1%81%D1%87%D1%91%D1%82.pdf" in got.headers["content-disposition"]


async def test_storage_reads_in_chunks_not_whole(container: Container) -> None:
    big = b"a" * (CHUNK * 2 + 10)
    await TEST_STORAGE.put("k", big, "application/pdf")
    chunks = [chunk async for chunk in TEST_STORAGE.stream("k")]
    assert [len(c) for c in chunks] == [CHUNK, CHUNK, 10]


async def test_new_version_keeps_old_ones_and_default_download_is_latest(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    first = (await upload(client, staff["manager"])).json()
    second = await upload(client, staff["manager"], PDF + b"v2", version_of=first["id"])
    assert second.status_code == 201, second.text
    ref = second.json()
    validate("FileRef", ref)
    assert (ref["id"], ref["version"]) == (first["id"], 2)

    latest = await client.get(f"/api/v1/files/{first['id']}", headers=staff["manager"].headers)
    old = await client.get(f"/api/v1/files/{first['id']}", params={"version": 1}, headers=staff["manager"].headers)
    assert (latest.content, old.content) == (PDF + b"v2", PDF)
    versions = (await client.get(f"/api/v1/files/{first['id']}/versions", headers=staff["manager"].headers)).json()
    validate("FileVersions", versions)
    assert [v["version"] for v in versions["items"]] == [2, 1]
    missing = await client.get(f"/api/v1/files/{first['id']}", params={"version": 9}, headers=staff["manager"].headers)
    assert_error(missing, 404, "NOT_FOUND")
    # чужую цепочку (не видна) новой версией не продолжить
    assert_error(await upload(client, staff["admin"], version_of=first["id"]), 404, "NOT_FOUND")


async def test_unbound_file_is_visible_only_to_uploader(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    ref = (await upload(client, staff["manager"])).json()
    for who in ("director", "accountant", "admin"):
        assert_error(await client.get(f"/api/v1/files/{ref['id']}", headers=staff[who].headers), 404, "NOT_FOUND")
        assert_error(
            await client.get(f"/api/v1/files/{ref['id']}/versions", headers=staff[who].headers), 404, "NOT_FOUND"
        )


async def test_file_attached_to_document_follows_document_visibility_and_is_journaled(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    ref = (await upload(client, staff["admin"])).json()
    doc = await create(client, staff["admin"], file_ids=[ref["id"]])
    assert [f["id"] for f in doc["files"]] == [ref["id"]]
    assert doc["journal"][-1] == {
        "at": doc["journal"][-1]["at"],
        "action": "file.attached",
        "by": {"crm_user_id": 9, "full_name": "Админ Админов"},
        "comment": None,
        "file_id": ref["id"],
        "version": 1,
    }
    # новая версия привязанного файла видна в документе; запись журнала «версия добавлена»
    await upload(client, staff["admin"], PDF + b"2", version_of=ref["id"])
    again = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["admin"].headers)).json()
    assert again["files"][0]["version"] == 2
    assert again["journal"][-1]["action"] == "file.version_added"

    # файл черновика, как и сам черновик, виден только автору (D1-10); после отправки registry.read видит и то, и другое
    assert_error(await client.get(f"/api/v1/files/{ref['id']}", headers=staff["manager"].headers), 404, "NOT_FOUND")
    assert (await submit(client, staff["admin"], doc["id"])).status_code == 200
    assert (await client.get(f"/api/v1/files/{ref['id']}", headers=staff["manager"].headers)).status_code == 200
    assert_error(await client.get(f"/api/v1/files/{ref['id']}", headers=staff["nobody"].headers), 403, "FORBIDDEN")
    outsider = await client.get(f"/api/v1/files/{ref['id']}", headers=staff["registrar"].headers)
    assert_error(outsider, 404, "NOT_FOUND")  # письма читает, но документ ему не виден


async def test_viewer_cannot_add_a_version_to_someone_elses_document_file(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    ref = (await upload(client, staff["admin"])).json()
    doc = await create(client, staff["admin"], file_ids=[ref["id"]])
    assert (await upload(client, staff["admin"], PDF + b"2", version_of=ref["id"])).status_code == 201
    assert (await submit(client, staff["admin"], doc["id"])).status_code == 200  # черновик чужим не виден (D1-10)
    # менеджер видит документ (registry.read) и может загружать файлы, но цепочку автора не продолжает
    denied = await upload(client, staff["manager"], PDF + b"3", version_of=ref["id"])
    assert_error(denied, 403, "FORBIDDEN", reason="not_file_owner")
    current = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["admin"].headers)).json()
    assert current["files"][0]["version"] == 2


async def test_file_attached_to_letter_is_visible_to_letter_readers(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    ref = (await upload(client, staff["registrar"])).json()
    letter = await client.post(
        "/api/v1/letters", json={**NEW_LETTER, "file_ids": [ref["id"]]}, headers=staff["registrar"].headers
    )
    assert letter.status_code == 201
    assert [f["id"] for f in letter.json()["files"]] == [ref["id"]]
    assert (await client.get(f"/api/v1/files/{ref['id']}", headers=staff["accountant"].headers)).status_code == 200
    assert_error(await client.get(f"/api/v1/files/{ref['id']}", headers=staff["admin"].headers), 404, "NOT_FOUND")


async def test_cannot_attach_foreign_missing_or_already_attached_file(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    mine = (await upload(client, staff["manager"])).json()
    theirs = (await upload(client, staff["supplier"])).json()
    for ids in ([theirs["id"]], ["00000000-0000-4000-8000-000000000009"]):
        bad = await client.post("/api/v1/documents", json={**MEMO, "file_ids": ids}, headers=staff["manager"].headers)
        assert_error(bad, 422, "VALIDATION_FAILED")
    await create(client, staff["manager"], file_ids=[mine["id"]])
    again = await client.post(
        "/api/v1/documents", json={**MEMO, "file_ids": [mine["id"]]}, headers=staff["manager"].headers
    )
    assert_error(again, 422, "VALIDATION_FAILED")  # уже привязан к другому документу


@pytest.mark.parametrize(
    ("content", "name", "content_type"),
    [
        (PDF, "a.pdf", "application/pdf"),
        (PNG, "a.png", "image/png"),
        (DOCX, "a.docx", DOCX_TYPE),
        (PDF, "scan.pdf", "application/octet-stream"),  # тип по расширению
    ],
)
async def test_allowed_types(
    client: httpx.AsyncClient, staff: dict[str, Person], content: bytes, name: str, content_type: str
) -> None:
    assert (await upload(client, staff["manager"], content, name=name, content_type=content_type)).status_code == 201


@pytest.mark.parametrize(
    ("content", "name", "content_type"),
    [
        (b"<html></html>", "a.html", "text/html"),
        (b"<html>%PDF-</html>", "a.pdf", "application/pdf"),  # заявлено PDF, содержимое — нет
        (PDF, "a.exe", "application/x-msdownload"),
        (PDF, "noext", "application/octet-stream"),
        (b"", "empty.pdf", "application/pdf"),
    ],
)
async def test_unsupported_types_are_415(
    client: httpx.AsyncClient, staff: dict[str, Person], content: bytes, name: str, content_type: str
) -> None:
    assert_error(
        await upload(client, staff["manager"], content, name=name, content_type=content_type),
        415,
        "UNSUPPORTED_MEDIA_TYPE",
    )


async def test_file_over_25_mb_is_413_and_missing_file_is_422(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    just_fits = b"%PDF-" + b"0" * (files_service.MAX_BYTES - 5)
    assert (await upload(client, staff["manager"], just_fits)).status_code == 201
    too_big = just_fits + b"0"
    assert_error(await upload(client, staff["manager"], too_big), 413, "PAYLOAD_TOO_LARGE")
    assert_error(await client.post("/api/v1/files", headers=staff["manager"].headers), 422, "VALIDATION_FAILED")


async def test_upload_is_idempotent_with_key(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    headers = {"Idempotency-Key": "upload-key-001"}
    one = await upload(client, staff["manager"], headers=headers)
    two = await upload(client, staff["manager"], headers=headers)
    assert (one.status_code, two.status_code, one.json() == two.json()) == (201, 201, True)
    assert len(TEST_STORAGE.objects) == 1
    other = await upload(client, staff["manager"], PNG, name="a.png", content_type="image/png", headers=headers)
    assert_error(other, 409, "CONFLICT", reason="idempotency_key_reused")


async def test_filename_cannot_carry_path_or_control_characters(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    ref = (await upload(client, staff["manager"], name="../../etc/pass\\wd\t.pdf")).json()
    assert not set("/\\\t") & set(ref["name"])
    assert all(key.startswith(f"files/{ref['id']}/") for key in TEST_STORAGE.objects)  # ключ не зависит от имени
    assert files_service.clean_name("a/b\\c\x00d") == "a_b_c_d"
    assert files_service.clean_name("  ..  ") == "file"


async def test_own_file_upload_only_role_uploads_and_reads_only_its_own_files(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """D1-2b: своя роль только с `crm.clients: full` (код `files.upload`) загружает письмо директору и читает свой
    файл; чужой файл и файл письма — 404, документы и реестр — 403."""
    from tests.helpers import seed_employee

    uploader = Person(21, "Заявочный Демо", ["files.upload"])
    await seed_employee(
        container,
        uploader.id,
        full_name=uploader.name,
        email="uploader@example.com",
        permissions={"eds": uploader.permissions},
    )
    response = await upload(client, uploader, name="pismo-direktoru.pdf")
    assert response.status_code == 201, response.text
    own = response.json()
    assert (await client.get(f"/api/v1/files/{own['id']}", headers=uploader.headers)).status_code == 200
    assert (await client.get(f"/api/v1/files/{own['id']}/versions", headers=uploader.headers)).status_code == 200

    foreign = (await upload(client, staff["manager"])).json()
    assert_error(await client.get(f"/api/v1/files/{foreign['id']}", headers=uploader.headers), 404, "NOT_FOUND")
    assert_error(await client.get("/api/v1/documents", headers=uploader.headers), 403, "FORBIDDEN")
