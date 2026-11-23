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
                "path": "Кабели",
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


# --- X-16: relevance of the classifier search (walk СЦ-2: «накладка» returned passenger transport and gas supply) ---


def _hit(code, name, group="", cls="", position="", sub=""):
    return {
        "mxikCode": code,
        "mxikName": name,
        "groupName": group,
        "className": cls,
        "positionName": position,
        "subPositionName": sub,
    }


WALK = [
    _hit("49100001001000000", "Перевозка пассажиров железнодорожным транспортом", "Услуги", "Накладка маршрутов"),
    _hit("35200001001000000", "Газоснабжение через магистральные сети", "Услуги", "Накладки на тарифы"),
    _hit("73020001000000000", "Детали железнодорожные", "Изделия из металла", "Накладки рельсовые"),  # group-level node
    _hit("73020010001000001", "Накладка рельсовая двухголовая", "Изделия из металла", "Детали железнодорожные"),
    _hit("73020010002000002", "Накладки для вагонов", "Изделия из металла", "Детали железнодорожные"),
    _hit("56100001001000000", "Фастфуд", "Услуги питания", "Накладка блюд"),
]


def _ask(text, hits, lang="ru"):
    from catalog.mxik import search

    reply = httpx.Response(200, json={"data": {"content": hits}}, request=httpx.Request("GET", "x"))
    with mock.patch("catalog.mxik.httpx.get", return_value=reply):
        return search(text, lang=lang)


def test_walk_word_finds_rail_parts_not_passenger_transport_or_gas():
    codes = [row["code"] for row in _ask("накладка", WALK)]
    assert "49100001001000000" not in codes and "35200001001000000" not in codes and "56100001001000000" not in codes
    assert set(codes) == {"73020010001000001", "73020010002000002"}, "the group node matches the word only in its path"


def test_product_level_code_ranks_above_group_node():
    group_node = _hit("73020000000000000", "Накладки рельсовые", "Изделия из металла")
    product = _hit("73020010001000001", "Накладки рельсовые", "Изделия из металла")
    rows = _ask("накладки", [group_node, product])
    assert [row["code"] for row in rows] == ["73020010001000001", "73020000000000000"]


def test_exact_word_in_name_ranks_above_prefix_and_path_only_match():
    prefix = _hit("11111111111111111", "Накладкодержатель")
    exact = _hit("22222222222222222", "Накладка рельсовая")
    path_only = _hit("33333333333333333", "Болт путевой", "Накладка и крепёж")
    rows = _ask("накладка", [prefix, path_only, exact])
    assert [row["code"] for row in rows] == ["22222222222222222", "11111111111111111"], "a path-only match is dropped"


def test_spellings_cyrillic_latin_new_and_old_find_the_same_position():
    hits = [_hit("44444444444444444", "Ўлчов асбоблари")]
    latin = [_hit("44444444444444444", "O‘lchov asboblari")]
    assert [r["code"] for r in _ask("олчов", hits)] == ["44444444444444444"]
    for query in ("o'lchov", "oʻlchov", "Ölchov", "o‘lchov"):
        assert [r["code"] for r in _ask(query, latin, lang="uz")] == ["44444444444444444"], query
    assert [r["code"] for r in _ask("асбоб", hits)] == ["44444444444444444"]


def test_result_shows_the_group_path_under_the_name():
    row = _ask("накладка", [WALK[3]])[0]
    assert row["path"] == "Изделия из металла › Детали железнодорожные"


def test_digit_query_keeps_classifier_order():
    rows = _ask("7302", WALK)
    assert [r["code"] for r in rows] == [h["mxikCode"] for h in WALK]
