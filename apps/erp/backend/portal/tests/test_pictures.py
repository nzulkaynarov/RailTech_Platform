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
