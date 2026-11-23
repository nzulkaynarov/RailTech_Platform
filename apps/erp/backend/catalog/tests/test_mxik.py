"""План 1.8: МХИК (ИКПУ) в карточке товара — подбор из классификатора Налогового комитета или ввод вручную."""

import json
from pathlib import Path
from unittest import mock

import httpx
import pytest

from catalog.tests.desk_world import build_world

pytestmark = pytest.mark.django_db

CODE = "08544001001000000"
HIT = {
    "mxikCode": CODE,
    "name": "Кабели силовые с медными жилами",
    "fullName": "Кабели силовые с медными жилами",
    "groupName": "Кабели",
    "unitsName": "метр",
    "packageName": "барабан",
}


@pytest.fixture
def world():
    return build_world()


def _search(world, who="supply", q="кабель"):
    return world["clients"][who].get("/api/v1/master-data/mxik/", {"q": q})


def test_search_returns_code_name_unit_and_package(world):
    reply = httpx.Response(200, json={"data": [HIT, {"mxikCode": "123"}]}, request=httpx.Request("GET", "x"))
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
    assert get.call_args.kwargs["params"]["search"] == "кабель"


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
        {"mxik_code": CODE, "mxik_name": HIT["name"], "mxik_unit": "метр", "mxik_package": "барабан"},
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
# The search address `mxik/search/by-params` ignored the word (the whole reference came back); `elasticsearch/search`
# filters by the word, and the fixtures below are its recorded real replies.

FIXTURES = Path(__file__).parent / "fixtures"
RAIL_NODE = (
    "07302001001000370"  # «Изделия из черных металлов, используемые для железнодорожных …» (word only in the name tail)
)
BRAKE_NODE = "06813002002000000"  # sub-position node «Накладка тормозная для автомобилей» — the word in its own name
BRAKE_PRODUCT = "06813002002002005"  # the product-level code under that node


def _recorded(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["data"]


def _hit(code, name, group="", cls="", position="", sub=""):
    return {
        "mxikCode": code,
        "name": name,
        "fullName": name,
        "groupName": group,
        "className": cls,
        "positionName": position,
        "subPositionName": sub,
    }


def _ask(text, hits, lang="ru"):
    from catalog.mxik import search

    reply = httpx.Response(200, json={"data": hits}, request=httpx.Request("GET", "x"))
    with mock.patch("catalog.mxik.httpx.get", return_value=reply):
        return search(text, lang=lang)


def test_walk_recorded_reply_for_the_word_ranks_product_codes_above_the_group_node():
    rows = _ask("накладка", _recorded("mxik_nakladka.json"))
    codes = [row["code"] for row in rows]
    assert not any(row["code"].startswith(("101", "351")) for row in rows), "no passenger transport or gas supply"
    assert RAIL_NODE in codes and BRAKE_NODE in codes
    node_at = codes.index(BRAKE_NODE)
    products = [c for c in codes if c.startswith("06813002002") and c != BRAKE_NODE]
    assert products and all(codes.index(c) < node_at for c in products), "product level goes above the group node"
    assert codes[0] != BRAKE_NODE, "the classifier lists the node first; the product-level code must lead"


def test_walk_prefix_noise_from_the_classifier_is_dropped():
    # «наклад» — the classifier returns melons and groats as well (fuzzy); only rows with the word stay.
    rows = _ask("накладка", _recorded("mxik_naklad_prefix.json"))
    assert rows and all("акладк" in (r["name"] + r["path"]).lower() for r in rows)
    assert not any("Дыни" in r["name"] or "Крупа" in r["name"] for r in rows)


def test_group_path_match_alone_is_dropped():
    hits = [
        _hit("49100001001000000", "Перевозка пассажиров", "Услуги", "Накладка маршрутов"),
        _hit("73020010001000001", "Накладка рельсовая двухголовая", "Изделия из металла", "", "Детали железнодорожные"),
    ]
    assert [r["code"] for r in _ask("накладка", hits)] == ["73020010001000001"]


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


@pytest.mark.parametrize("query", ["oʻlchov", "ölchov", "Ölchov", "o‘lchov"])
def test_view_sends_uzbek_word_in_classifier_spelling_with_uzbek_language(world, query):
    reply = httpx.Response(200, json={"data": []}, request=httpx.Request("GET", "x"))
    with mock.patch("catalog.mxik.httpx.get", return_value=reply) as get:
        assert _search(world, q=query).status_code == 200
    params = get.call_args.kwargs["params"]
    assert params["lang"] == "uz_latn", "a non-ASCII Uzbek spelling must not be sent as Russian"
    assert params["search"].lower() == "o'lchov"


def test_view_cyrillic_query_goes_to_the_russian_classifier(world):
    reply = httpx.Response(200, json={"data": []}, request=httpx.Request("GET", "x"))
    with mock.patch("catalog.mxik.httpx.get", return_value=reply) as get:
        _search(world, q="накладка")
    assert get.call_args.kwargs["params"]["lang"] == "ru"
    assert get.call_args.kwargs["params"]["search"] == "накладка"


def test_result_shows_the_group_path_under_the_name():
    row = _ask(
        "накладка",
        [_hit("73020010001000001", "Накладка рельсовая", "Изделия из металла", "", "Детали железнодорожные")],
    )[0]
    assert row["path"] == "Изделия из металла › Детали железнодорожные"


def test_digit_query_keeps_classifier_order():
    hits = _recorded("mxik_nakladka.json")
    assert [r["code"] for r in _ask("7302", hits)] == [h["mxikCode"] for h in hits]
