"""Порядок реестра и списка документов по полю (Х-15б, pg): курсор несёт порядок, пустые в конце, белый список."""

from typing import Any

import httpx
import pytest

from app.container import Container
from tests.domain import Person
from tests.signing import sign_out
from tests.test_api_auth import assert_error
from tests.test_documents import MEMO, create, submit
from tests.test_letterhead_letters import deliver_letterhead
from tests.test_reply_path import reply_draft

pytestmark = pytest.mark.pg

AMOUNTS = {"B": "500.00", "C": "1500.00", "D": "20.00"}  # у "A" суммы нет


async def seed(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    who = staff["manager"]
    await create(client, who, subject="A без суммы")
    for letter, amount in AMOUNTS.items():
        await create(client, who, subject=f"{letter} с суммой", amount={"amount": amount, "currency": "UZS"})
    # письмо на подписи: номера нет до регистрации — «пустое» значение номера
    await create(client, staff["registrar"], kind="letter_out", subject="E без номера", recipient={"name": "ООО «Е»"})


async def walk(
    client: httpx.AsyncClient, who: Person, url: str, sort: str | None, limit: int = 2, **params: Any
) -> list[dict[str, Any]]:
    """Все страницы подряд по курсору; на каждой странице курсор — тот, что вернула предыдущая."""
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(10):
        query = {**params, "limit": limit, **({"sort": sort} if sort else {}), **({"cursor": cursor} if cursor else {})}
        response = await client.get(url, params=query, headers=who.headers)
        assert response.status_code == 200, response.text
        page = response.json()
        rows += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return rows
    raise AssertionError("cursor did not end")


@pytest.mark.parametrize("url", ["/api/v1/registry", "/api/v1/documents"])
async def test_amount_order_walks_pages_with_empty_last(
    client: httpx.AsyncClient, staff: dict[str, Person], url: str
) -> None:
    await seed(client, staff)
    who = staff["manager"]
    kinds = {"kind": "memo"}
    asc = await walk(client, who, url, "amount", **kinds)
    desc = await walk(client, who, url, "-amount", **kinds)
    value = lambda row: row["amount"]["amount"] if row["amount"] else None  # noqa: E731
    assert [value(r) for r in asc] == ["20.00", "500.00", "1500.00", None]
    assert [value(r) for r in desc] == ["1500.00", "500.00", "20.00", None]  # пустое — в конце и при «вниз»
    assert len({r["id"] for r in asc}) == 4  # ни потерь, ни повторов на стыке страниц


@pytest.mark.parametrize("url", ["/api/v1/registry", "/api/v1/documents"])
async def test_equal_values_keep_id_tiebreak_across_pages(
    client: httpx.AsyncClient, staff: dict[str, Person], url: str
) -> None:
    who = staff["manager"]
    for _ in range(5):
        await create(client, who, subject="Одинаковая тема")  # равное значение поля: порядок держит id
    rows = await walk(client, who, url, "subject", limit=2, kind="memo")
    assert len(rows) == 5 and len({r["id"] for r in rows}) == 5
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids)
    back = await walk(client, who, url, "-subject", limit=2, kind="memo")
    assert [r["id"] for r in back] == sorted(ids, reverse=True)


async def test_missing_number_goes_last_both_ways(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    who = staff["registrar"]  # реестр ему закрыт, а свой список документов — нет
    sent = await create(client, who, kind="letter_out", subject="Отправленное", recipient={"name": "ООО «А»"})
    await sign_out(client, staff, sent["id"])  # номер выдан при регистрации
    await create(client, who, kind="letter_out", subject="Черновик без номера", recipient={"name": "ООО «Б»"})
    for sort in ("number", "-number"):
        rows = await walk(client, who, "/api/v1/documents", sort, kind="letter_out")
        assert len(rows) >= 2 and rows[-1]["number"] is None and all(r["number"] for r in rows[:-1])


async def test_sort_by_created_matches_default_for_newest_first(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await seed(client, staff)
    who = staff["manager"]
    default = await walk(client, who, "/api/v1/registry", None, kind="memo")
    newest = await walk(client, who, "/api/v1/registry", "-created", kind="memo")
    assert [r["id"] for r in newest] == [r["id"] for r in default]


async def test_field_outside_allow_list_is_rejected(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    who = staff["manager"]
    for url in ("/api/v1/registry", "/api/v1/documents"):
        for bad in ("author_crm_user_id", "-id", "number;drop", "NUMBER"):
            response = await client.get(url, params={"sort": bad}, headers=who.headers)
            assert_error(response, 422, "VALIDATION_FAILED")


async def test_cursor_of_another_order_is_rejected(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    await seed(client, staff)
    who = staff["manager"]
    first = await client.get(
        "/api/v1/registry", params={"sort": "amount", "limit": 1, "kind": "memo"}, headers=who.headers
    )
    cursor = first.json()["next_cursor"]
    assert cursor
    other = await client.get(
        "/api/v1/registry", params={"sort": "-amount", "cursor": cursor, "kind": "memo"}, headers=who.headers
    )
    assert_error(other, 422, "VALIDATION_FAILED")
    plain = await client.get("/api/v1/registry", params={"cursor": cursor}, headers=who.headers)
    assert_error(plain, 422, "VALIDATION_FAILED")


async def test_number_sorts_as_opaque_string(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    """У номера документа нет сохранённого порядкового поля: порядок строковый, число в номере не разбирается."""
    await seed(client, staff)
    rows = await walk(client, staff["manager"], "/api/v1/registry", "number", kind="memo")
    numbers = [r["number"] for r in rows]
    assert numbers == sorted(numbers)
    assert MEMO["kind"] == "memo"


@pytest.mark.parametrize("url", ["/api/v1/registry", "/api/v1/documents"])
@pytest.mark.parametrize("glyph", ["語", "😀"])
async def test_long_multibyte_subject_does_not_break_the_cursor(
    client: httpx.AsyncClient, staff: dict[str, Person], url: str, glyph: str
) -> None:
    """Курсор не несёт значение поля: тема из 300 знаков по 3–4 байта не выводит его за предел длины."""
    who = staff["manager"]
    for index in range(3):
        await create(client, who, subject=glyph * 299 + str(index))
    for sort in ("subject", "-subject"):
        first = await client.get(url, params={"sort": sort, "limit": 1, "kind": "memo"}, headers=who.headers)
        assert first.status_code == 200, first.text
        assert len(first.json()["next_cursor"]) < 200
        rows = await walk(client, who, url, sort, limit=1, kind="memo")
        subjects = [r.get("subject") or r["title"] for r in rows]
        assert subjects == sorted(subjects, reverse=sort.startswith("-")) and len(set(subjects)) == 3


async def test_status_order_follows_the_word_derived_from_facts(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    """«На подписи» — факт письма (`draft` + передача на подпись): стоит рядом со словом, а не среди черновиков."""
    await deliver_letterhead(client, container)
    manager = staff["manager"]
    await create(client, manager, subject="M черновик служебки")
    plain = await create(client, manager, kind="letter_out", subject="L черновик письма", recipient={"name": "ООО «А»"})
    handed = await reply_draft(client, manager, None)
    ok = await client.post(f"/api/v1/documents/{handed['id']}/registration-request", headers=manager.headers)
    assert ok.status_code == 200, ok.text
    submitted = await create(client, manager, subject="N на согласовании")
    assert (await submit(client, manager, submitted["id"])).status_code == 200

    def words(rows: list[dict[str, Any]]) -> list[str]:
        return ["signing" if r["awaiting_signature"] else r["status"] for r in rows]

    for url in ("/api/v1/registry", "/api/v1/documents"):
        for sort, reverse in (("status", False), ("-status", True)):
            rows = [r for r in await walk(client, manager, url, sort, limit=2) if r["kind"] in ("memo", "letter_out")]
            order = words(rows)
            expected = sorted(order, key=["draft", "signing", "on_approval"].index, reverse=reverse)
            assert order == expected, (url, sort, order)
            assert order.count("signing") == 1 and order.count("draft") >= 2
    assert plain["awaiting_signature"] is False
