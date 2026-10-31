"""«Проверить» внешней копии на Яндекс Диске (OPS-YADISK): логин, папка, пароль приложения, WebDAV.

Сеть подменена заглушкой WebDAV (`httpx.MockTransport`): папки, файлы, Basic-авторизация и коды
ошибок Яндекса (401, 403, 507). Пароли — явно фиктивные, собраны из частей.
"""

import asyncio
import base64
from dataclasses import dataclass, field
from urllib.parse import unquote

import httpx
import pytest

from app.domain import yadisk
from app.integrations import yadisk as yadisk_api

LOGIN = "backup@example.org"
# Пароль приложения Яндекса — 16 строчных латинских букв; здесь — заведомо фиктивный.
APP_PASSWORD = "fake" + "fake" + "fake" + "fake"
COLLECTION = (
    '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop>'
    "<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>"
    "</d:multistatus>"
)
FILE = (
    '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop>'
    "<d:resourcetype/></d:prop></d:propstat></d:response></d:multistatus>"
)


@dataclass
class FakeDav:
    """Диск в памяти: папки и файлы по пути; `status` — ответ на определённый метод."""

    password: str = APP_PASSWORD
    dirs: set[str] = field(default_factory=lambda: {""})
    files: set[str] = field(default_factory=set)
    status: dict[str, int] = field(default_factory=dict)
    seen: list[tuple[str, str]] = field(default_factory=list)
    auth: list[str] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path).strip("/")
        method = request.method
        self.seen.append((method, path))
        self.auth.append(request.headers.get("Authorization", ""))
        expected = base64.b64encode(f"{LOGIN}:{self.password}".encode()).decode()
        if request.headers.get("Authorization") != f"Basic {expected}":
            return httpx.Response(401)
        if method in self.status:
            return httpx.Response(self.status[method])
        if method == "PROPFIND":
            if path in self.dirs:
                return httpx.Response(207, text=COLLECTION)
            if path in self.files:
                return httpx.Response(207, text=FILE)
            return httpx.Response(404)
        if method == "MKCOL":
            if path in self.dirs or path in self.files:
                return httpx.Response(405)
            if path.rpartition("/")[0] not in self.dirs:
                return httpx.Response(409)
            self.dirs.add(path)
            return httpx.Response(201)
        if method == "PUT":
            self.files.add(path)
            return httpx.Response(201)
        if method == "DELETE":
            if path not in self.files:
                return httpx.Response(404)
            self.files.discard(path)
            return httpx.Response(204)
        return httpx.Response(405)


def run(
    dav: FakeDav, folder: str = "RailTech-backups/prod", password: str = APP_PASSWORD
) -> yadisk.ProbeResult:
    return asyncio.run(
        yadisk_api.probe(LOGIN, password, folder, transport=httpx.MockTransport(dav.handler))
    )


# --- чистые функции -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" Backup@Example.ORG ", "backup@example.org"),
        ("backup@railtech.uz", "backup@railtech.uz"),
        ("backup", None),
        ("a b@example.org", None),
        ('a"b@example.org', None),
        ("a#b@example.org", None),
        ("backup@почта.рф", "backup@почта.рф"),
        ("", None),
    ],
)
def test_login_is_an_email(value: str, expected: str | None) -> None:
    assert yadisk.normalize_login(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("RailTech-backups/prod", "RailTech-backups/prod"),
        (" /RailTech-backups//prod/ ", "RailTech-backups/prod"),
        ("disk:/Бэкапы/база (прод)", "Бэкапы/база (прод)"),
        ("a\\b", "a/b"),
        ("../etc", None),
        ("a/./b", None),
        ('a"b', None),
        ("a$b", None),
        ("/", None),
        ("x" * 101, None),
    ],
)
def test_folder_path_is_safe_for_settings_and_shell(value: str, expected: str | None) -> None:
    assert yadisk.normalize_folder(value) == expected


def test_default_folder_is_per_environment() -> None:
    assert yadisk.default_folder("prod") == "RailTech-backups/prod"


def test_app_password_spaces_are_dropped_and_shape_is_recognised() -> None:
    grouped = " ".join(APP_PASSWORD[i : i + 4] for i in range(0, 16, 4))
    assert yadisk.normalize_password(grouped) == APP_PASSWORD
    assert yadisk.looks_like_app_password(APP_PASSWORD)
    assert not yadisk.looks_like_app_password("Not-An-App-Pass1")


@pytest.mark.parametrize(
    ("status", "password", "reason"),
    [
        (200, APP_PASSWORD, None),
        (207, APP_PASSWORD, None),
        (401, APP_PASSWORD, "auth_failed"),
        (401, "Account-Pass-0", "not_app_password"),
        (403, APP_PASSWORD, "webdav_forbidden"),
        (507, APP_PASSWORD, "no_space"),
        (429, APP_PASSWORD, "network"),
        (503, APP_PASSWORD, "network"),
    ],
)
def test_webdav_status_to_reason(status: int, password: str, reason: str | None) -> None:
    result = yadisk.classify_status(status, password)
    assert (result.reason if result else None) == reason


# --- «Проверить» по WebDAV ------------------------------------------------------------------------


def test_missing_folder_is_created_along_the_path_and_write_is_checked() -> None:
    dav = FakeDav()
    result = run(dav)
    assert result == yadisk.ProbeResult("ok", "RailTech-backups/prod")
    assert {"RailTech-backups", "RailTech-backups/prod"} <= dav.dirs
    methods = [m for m, _ in dav.seen]
    assert methods == ["PROPFIND", "PROPFIND", "MKCOL", "MKCOL", "PUT", "DELETE"]
    assert dav.files == set()  # проверочный файл удалён


def test_existing_folder_is_not_recreated() -> None:
    dav = FakeDav(dirs={"", "RailTech-backups", "RailTech-backups/prod"})
    assert run(dav).ok
    assert "MKCOL" not in [m for m, _ in dav.seen]


def test_cyrillic_folder_is_url_encoded() -> None:
    dav = FakeDav()
    assert run(dav, "Бэкапы/прод").ok
    assert "Бэкапы/прод" in dav.dirs


def test_wrong_app_password_is_auth_failed() -> None:
    dav = FakeDav(password="other" + "fake" + "fake" + "abc")
    assert run(dav).reason == "auth_failed"
    assert [m for m, _ in dav.seen] == ["PROPFIND"]


def test_account_password_instead_of_app_password_is_named() -> None:
    assert run(FakeDav(), password="Account-Pass-0").reason == "not_app_password"


def test_webdav_closed_by_the_360_admin() -> None:
    assert run(FakeDav(status={"PROPFIND": 403})).reason == "webdav_forbidden"


def test_no_space_on_disk_when_writing() -> None:
    dav = FakeDav(dirs={"", "RailTech-backups", "RailTech-backups/prod"}, status={"PUT": 507})
    assert run(dav).reason == "no_space"


def test_no_space_when_creating_the_folder() -> None:
    assert run(FakeDav(status={"MKCOL": 507})).reason == "no_space"


def test_folder_path_pointing_to_a_file_is_not_a_folder() -> None:
    dav = FakeDav(dirs={"", "RailTech-backups"}, files={"RailTech-backups/prod"})
    assert run(dav).reason == "not_folder"


def test_network_errors_are_network() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    result = asyncio.run(
        yadisk_api.probe(LOGIN, APP_PASSWORD, "x", transport=httpx.MockTransport(broken))
    )
    assert (result.reason, result.detail) == ("network", "ConnectError")


def test_password_travels_only_as_basic_auth_to_webdav() -> None:
    dav = FakeDav()
    run(dav)
    assert all(a.startswith("Basic ") for a in dav.auth)
    assert all(APP_PASSWORD not in path for _, path in dav.seen)
