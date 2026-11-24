"""ЕД-5 и СУЩ-3: логотип контрагента и фото его контакта.

Что проверяется: наружу уходит только версия (адресов хранилища нет), загрузка меняет версию, чужой тип и размер
отклоняются, правят только те, кто правит реквизиты (`deal.manage` или `supply.manage`), в Кабинете — администратор
компании. Мир — `catalog.tests.desk_world` и фикстуры портала.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from parties.models import Company, Contact
from PIL import Image
from portal.tests.conftest import PortalAPIClient  # noqa: F401
from portal.tests.conftest import make_portal_session

from catalog.tests.desk_world import build_world

pytestmark = pytest.mark.django_db

ORGS = "/api/v1/parties/organizations/"
PEOPLE = "/api/v1/parties/people/"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def picture(fmt="PNG", size=(300, 200), color=(200, 30, 30), name=None, content_type=None):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format=fmt)
    extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[fmt]
    name = name or f"pic.{extension}"
    return SimpleUploadedFile(name, out.getvalue(), content_type=content_type or f"image/{fmt.lower()}")


@pytest.fixture
def world():
    world = build_world()
    Contact.objects.create(
        company=world["supplier"], name="Рустам Ахмедов", position="Снабжение", phone="+998", is_primary=True
    )
    return world


def put(client, url, file):
    return client.put(url, {"file": file}, format="multipart")


def card(world, who="supply"):
    return world["clients"][who].get(f"{ORGS}{world['supplier'].pk}/").json()


# --- логотип контрагента --------------------------------------------------------------------------------------


def test_logo_upload_exposes_version_only_and_serves_square_webp(world):
    api = world["clients"]["supply"]
    url = f"{ORGS}{world['supplier'].pk}/logo/"
    assert card(world)["logo_version"] is None
    assert api.get(url).status_code == 404

    response = put(api, url, picture())
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["logo_version"] and len(body["logo_version"]) == 10
    # адресов хранилища в карточке нет
    assert (
        "/media/" not in str(body)
        and "http" not in str(body["logo_version"])
        and "logo" not in body.keys() - {"logo_version"}
    )

    small = api.get(url)
    assert small["Content-Type"] == "image/webp"
    assert Image.open(io.BytesIO(small.content)).size == (96, 96)
    assert Image.open(io.BytesIO(api.get(url, {"size": "full"}).content)).size == (256, 256)


def test_logo_version_changes_after_replace_and_clears_on_remove(world):
    api = world["clients"]["supply"]
    url = f"{ORGS}{world['supplier'].pk}/logo/"
    first = put(api, url, picture()).json()["logo_version"]
    second = put(api, url, picture(color=(10, 10, 200))).json()["logo_version"]
    assert second and second != first
    removed = api.delete(url)
    assert removed.status_code == 200 and removed.json()["logo_version"] is None
    assert api.get(url).status_code == 404
    assert api.delete(url).status_code == 200  # повтор безопасен
    world["supplier"].refresh_from_db()
    assert not world["supplier"].logo


@pytest.mark.parametrize(
    "file, code",
    [
        (
            SimpleUploadedFile("logo.svg", b"<svg onload=alert(1)/>", content_type="image/svg+xml"),
            "FILE_TYPE_NOT_ALLOWED",
        ),
        (SimpleUploadedFile("logo.gif", b"GIF89a....", content_type="image/gif"), "FILE_TYPE_NOT_ALLOWED"),
        (SimpleUploadedFile("logo.png", b"not a picture at all", content_type="image/png"), "FILE_CONTENT_MISMATCH"),
        (
            SimpleUploadedFile("logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, content_type="image/png"),
            "FILE_CONTENT_MISMATCH",
        ),
        (
            SimpleUploadedFile(
                "logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024 + 1), content_type="image/png"
            ),
            "FILE_TOO_LARGE",
        ),
    ],
)
def test_logo_rejects_wrong_type_and_size(world, file, code):
    api = world["clients"]["supply"]
    response = put(api, f"{ORGS}{world['supplier'].pk}/logo/", file)
    assert response.status_code == 400 and response.json()["detail"] == code, response.content
    world["supplier"].refresh_from_db()
    assert not world["supplier"].logo


def test_logo_needs_a_file(world):
    response = world["clients"]["supply"].put(f"{ORGS}{world['supplier'].pk}/logo/", {}, format="multipart")
    assert response.status_code == 400


def test_logo_edit_is_for_requisite_editors_only(world):
    url = f"{ORGS}{world['supplier'].pk}/logo/"
    put(world["clients"]["supply"], url, picture())
    for who in ("manager", "accountant"):
        assert put(world["clients"][who], url, picture()).status_code == 403
        assert world["clients"][who].delete(url).status_code == 403
        assert world["clients"][who].get(url).status_code == 200  # смотреть может любой сотрудник
    world["supplier"].refresh_from_db()
    assert world["supplier"].logo  # отказы файл не тронули


def test_logo_of_a_stranger_company_is_not_reachable(world):
    stranger = Company.objects.create(name="ООО Чужой", inn="300000999")
    url = f"{ORGS}{stranger.pk}/logo/"
    assert put(world["clients"]["supply"], url, picture()).status_code == 404
    assert world["clients"]["supply"].get(url).status_code == 404


def test_logo_versions_batch_and_list_row(world):
    api = world["clients"]["supply"]
    stranger = Company.objects.create(name="ООО Чужой", inn="300000999")
    put(api, f"{ORGS}{world['supplier'].pk}/logo/", picture())
    ids = f"{world['supplier'].pk},{stranger.pk},999999,bad"
    got = api.get(f"{ORGS}logos/", {"ids": ids}).json()["results"]
    assert list(got) == [str(world["supplier"].pk)] and got[str(world["supplier"].pk)]
    rows = api.get(ORGS, {"q": "Поставщик"}).json()["results"]
    assert rows[0]["logo_version"] == got[str(world["supplier"].pk)]


# --- фото контакта ---------------------------------------------------------------------------------------------


def test_contact_photo_roundtrip_and_no_public_address(world):
    api = world["clients"]["supply"]
    contact = Contact.objects.get(company=world["supplier"])
    url = f"{PEOPLE}{contact.pk}/photo/"
    assert api.get(url).status_code == 404
    first = put(api, url, picture(size=(256, 256))).json()
    assert first["id"] == contact.pk and first["photo_version"]
    assert Image.open(io.BytesIO(api.get(url).content)).size == (96, 96)
    # версия видна в списке «Люди», в карточке контрагента и в списке людей компании
    listed = api.get(PEOPLE).json()["results"][0]
    assert listed["photo_version"] == first["photo_version"]
    assert card(world)["people"][0]["photo_version"] == first["photo_version"]
    people = api.get(f"{ORGS}{world['supplier'].pk}/people/").json()["results"][0]
    assert people["photo_version"] == first["photo_version"]
    assert "/media/" not in str(listed) and "contacts/" not in str(listed)

    second = put(api, url, picture(size=(256, 256), color=(1, 2, 3))).json()
    assert second["photo_version"] != first["photo_version"]
    assert api.delete(url).json()["photo_version"] is None
    assert api.get(url).status_code == 404


def test_contact_photo_rejects_wrong_type_and_is_permissioned(world):
    contact = Contact.objects.get(company=world["supplier"])
    url = f"{PEOPLE}{contact.pk}/photo/"
    bad = SimpleUploadedFile("p.svg", b"<svg/>", content_type="image/svg+xml")
    refused = put(world["clients"]["supply"], url, bad)
    assert refused.status_code == 400 and refused.json()["detail"] == "FILE_TYPE_NOT_ALLOWED"
    assert put(world["clients"]["manager"], url, picture()).status_code == 403
    assert world["clients"]["manager"].delete(url).status_code == 403
    contact.refresh_from_db()
    assert not contact.photo


# --- Кабинет: «Компания» ---------------------------------------------------------------------------------------


def test_cabinet_admin_replaces_company_logo(portal_client, client_company):
    assert portal_client.get("/api/portal/v1/company").json()["logo_version"] is None
    assert portal_client.get("/api/portal/v1/company/logo").status_code == 404
    response = portal_client.put("/api/portal/v1/company/logo", {"file": picture()}, format="multipart")
    assert response.status_code == 200, response.content
    version = response.json()["logo_version"]
    assert version
    served = portal_client.get("/api/portal/v1/company/logo")
    assert served.status_code == 200 and served["Content-Type"] == "image/webp"
    assert "/media/" not in str(portal_client.get("/api/portal/v1/company").json())
    again = portal_client.put("/api/portal/v1/company/logo", {"file": picture(color=(1, 9, 9))}, format="multipart")
    assert again.json()["logo_version"] != version
    assert portal_client.delete("/api/portal/v1/company/logo").json()["logo_version"] is None


def test_cabinet_logo_rejects_wrong_type_and_non_admin(portal_client, readonly_portal_client, client_company):
    bad = SimpleUploadedFile("l.gif", b"GIF89a....", content_type="image/gif")
    refused = portal_client.put("/api/portal/v1/company/logo", {"file": bad}, format="multipart")
    assert refused.status_code == 422 and refused.json()["detail"] == "FILE_TYPE_NOT_ALLOWED"
    # участник без права действовать — отказ; он же читает
    assert (
        readonly_portal_client.put("/api/portal/v1/company/logo", {"file": picture()}, format="multipart").status_code
        == 403
    )
    assert readonly_portal_client.delete("/api/portal/v1/company/logo").status_code == 403
    client_company.refresh_from_db()
    assert not client_company.logo


def test_cabinet_non_admin_with_can_act_gets_admin_required(client_company, client_contact):
    colleague = Contact.objects.create(
        company=client_company, name="Коллега", email="c@example.uz", can_act=True, is_admin=False
    )
    client = PortalAPIClient()
    session = make_portal_session(colleague, client_company, "magic_link")
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    response = client.put("/api/portal/v1/company/logo", {"file": picture()}, format="multipart")
    assert response.status_code == 409 and response.json()["detail"] == "ADMIN_REQUIRED"


# --- закрытое хранилище и «бомбы» ------------------------------------------------------------------------------


def test_hostile_png_with_huge_dimensions_is_refused_before_decoding(world):
    """Файл в сотни байт с заголовком 12000×12000 не должен распаковываться (~430 МБ в RGBA): отказ по размерам."""
    import struct
    import zlib

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    side = 12000
    header = struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00" * (side * 3 + 1) * 4)  # лишь несколько строк: заголовок врёт о размере
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
    assert len(png) < 5000
    bomb = SimpleUploadedFile("bomb.png", png, content_type="image/png")
    response = put(world["clients"]["supply"], f"{ORGS}{world['supplier'].pk}/logo/", bomb)
    assert response.status_code == 400 and response.json()["detail"] == "IMAGE_TOO_LARGE", response.content
    world["supplier"].refresh_from_db()
    assert not world["supplier"].logo


def test_company_logo_is_private_and_never_leaves_as_a_storage_path(world):
    """`Company.logo` лежит в закрытом хранилище; везде наружу выходит только наш версионный путь API."""
    from catalog.serializers import CompanyLightSerializer
    from core.storage import get_private_storage

    supplier = world["supplier"]
    put(world["clients"]["supply"], f"{ORGS}{supplier.pk}/logo/", picture())
    supplier.refresh_from_db()
    assert supplier._meta.get_field("logo").storage is get_private_storage() or (
        supplier._meta.get_field("logo").storage.__class__ is get_private_storage().__class__
    )
    shown = CompanyLightSerializer(supplier).data["logo"]
    assert shown == f"/api/v1/parties/organizations/{supplier.pk}/logo/?v={pictures_version(supplier)}"
    assert "/media/" not in shown and supplier.logo.name not in shown
    # публичный список медиа больше не отдаёт файл логотипа компании
    from django.test import Client

    assert Client().get(f"/media/{supplier.logo.name}").status_code == 404


def pictures_version(company):
    from parties import pictures

    return pictures.version(company.logo)


def test_operator_logo_is_public_through_the_api_only(client_company, anon_portal_client):
    from parties import pictures

    from catalog.desk.items import ItemError  # noqa: F401
    from core.tenant import own_company  # noqa: F401

    client_company.logo = None
    pictures.replace(client_company, "logo", picture())
    from unittest import mock

    with mock.patch("core.tenant.own_company", return_value=client_company):
        info = anon_portal_client.get("/api/portal/v1/operator").json()
        assert info["logo_url"] == f"/api/portal/v1/operator/logo?v={pictures_version(client_company)}"
        served = anon_portal_client.get("/api/portal/v1/operator/logo")
    assert served.status_code == 200 and served["Content-Type"] == "image/webp"


# --- миграция 0036: логотип уезжает из публичного бакета в закрытый ---------------------------------------------


def test_migration_moves_company_logo_from_public_to_private_storage(
    tmp_path, client_company, anon_portal_client, settings
):
    """Прод: у компании-оператора логотип лежит в публичном бакете; после 0035 его должен найти закрытый."""
    import importlib
    from unittest import mock

    from django.apps import apps
    from django.core.files.storage import FileSystemStorage

    migration = importlib.import_module("parties.migrations.0036_move_company_logos_to_private")
    public = FileSystemStorage(location=str(tmp_path / "public"))
    private = FileSystemStorage(location=str(tmp_path / "private"))
    out = io.BytesIO()
    Image.new("RGB", (30, 30), (5, 6, 7)).save(out, format="WEBP")
    name = f"companies/{client_company.pk}/logo/old.webp"
    public.save(name, io.BytesIO(out.getvalue()))
    Company.objects.filter(pk=client_company.pk).update(logo=name)
    settings.OWN_COMPANY_ID = client_company.pk

    def serve():
        company = Company.objects.get(pk=client_company.pk)
        with mock.patch.object(company._meta.get_field("logo"), "storage", private):
            company.logo.storage = private
            with mock.patch("core.tenant.own_company", return_value=company):
                return anon_portal_client.get("/api/portal/v1/operator/logo")

    assert serve().status_code == 404  # до шага данных закрытое хранилище файла не знает

    with mock.patch.object(migration, "_storages", return_value=(public, private)):
        migration.forward(apps, None)
        assert private.exists(name) and not public.exists(name)
        migration.forward(apps, None)  # повтор безопасен
        assert private.exists(name)
    assert serve().status_code == 200

    with mock.patch.object(migration, "_storages", return_value=(public, private)):
        migration.backward(apps, None)
    assert public.exists(name) and not private.exists(name)
