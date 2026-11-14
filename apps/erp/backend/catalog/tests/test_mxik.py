"""План 1.8: МХИК (ИКПУ) в карточке товара — подбор из классификатора Налогового комитета или ввод вручную."""

from unittest import mock

import httpx
import pytest

from catalog.tests.desk_world import build_world

pytestmark = pytest.mark.django_db

CODE = "08544001001000000"
HIT = {
    "mxikCode": CODE,
    "mxikName": "Кабели силовые с медными жилами",
    "groupName": "Кабели",
    "unitName": "метр",
    "packages": [{"code": "1", "nameRu": "барабан", "unitName": "метр"}],
}


@pytest.fixture
def world():
    return build_world()


def _search(world, who="supply", q="кабель"):
    return world["clients"][who].get("/api/v1/master-data/mxik/", {"q": q})


def test_search_returns_code_name_unit_and_package(world):
    reply = httpx.Response(
        200, json={"data": {"content": [HIT, {"mxikCode": "123"}]}}, request=httpx.Request("GET", "x")
    )
    with mock.patch("catalog.mxik.httpx.get", return_value=reply) as get:
        response = _search(world)
    assert response.status_code == 200, response.content
    assert response.json() == {
        "results": [
            {
                "code": CODE,
                "name": "Кабели силовые с медными жилами",
                "group": "Кабели",
                "unit": "метр",
                "package": "барабан",
            }
        ]
    }, "строка без 17-значного кода отбрасывается"
    assert get.call_args.kwargs["params"]["searchText"] == "кабель"


def test_unavailable_classifier_is_503_and_short_query_asks_nothing(world):
    with mock.patch("catalog.mxik.httpx.get", side_effect=httpx.ConnectError("down")):
        response = _search(world)
    assert response.status_code == 503 and response.json() == {"detail": "MXIK_UNAVAILABLE"}
    with mock.patch("catalog.mxik.httpx.get") as get:
        assert _search(world, q="к").json() == {"results": []}
    get.assert_not_called()


def test_code_from_the_classifier_or_by_hand_is_kept_on_the_item(world):
    path = f"/api/v1/catalog/items/{world['cable'].pk}/"
    client = world["clients"]["supply"]
    chosen = client.patch(
        path,
        {"mxik_code": CODE, "mxik_name": HIT["mxikName"], "mxik_unit": "метр", "mxik_package": "барабан"},
        format="json",
    )
    assert chosen.status_code == 200, chosen.content
    assert client.get(path).json()["mxik"] == {
        "code": CODE,
        "name": "Кабели силовые с медными жилами",
        "unit": "метр",
        "package": "барабан",
    }

    bad = client.patch(path, {"mxik_code": "0854"}, format="json")
    assert bad.status_code == 400

    cleared = client.patch(path, {"mxik_code": ""}, format="json")
    assert cleared.status_code == 200
    assert client.get(path).json()["mxik"] is None, "без кода — ни названия, ни единицы"
