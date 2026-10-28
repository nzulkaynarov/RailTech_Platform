"""Эталонные документы для тестов: демо-бланк и тела (все реквизиты вымышленные)."""

from __future__ import annotations

import struct
import zlib
from datetime import date
from decimal import Decimal
from typing import Any

from rt_docs.model import DocumentMeta, Letterhead, Logo, Money, Value

Node = dict[str, Any]


def png(width: int = 96, height: int = 32, rgb: tuple[int, int, int] = (21, 41, 77)) -> bytes:
    """Однотонный PNG без Pillow — логотип демо-бланка."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * width
    raw = zlib.compress(row * height)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


LETTERHEAD = Letterhead(
    company_name="ООО «Демо Рельс Сервис»",
    requisites=(
        "100000, г. Ташкент, ул. Примерная, 1 · ИНН 000 000 000",
        "р/с 0000 0000 0000 0000 0000 в АКБ «Демобанк», МФО 00000 · +998 00 000-00-00 · info@example.org",
    ),
    footer=(
        "ООО «Демо Рельс Сервис» · 100000, г. Ташкент, ул. Примерная, 1 · ИНН 000 000 000",
        "р/с 0000 0000 0000 0000 0000 в АКБ «Демобанк», МФО 00000 · +998 00 000-00-00 · info@example.org",
    ),
    logo=Logo(png(), "image/png"),
)

UZ_TEXT = "Oʻzbekiston Respublikasi, gʻalla, qoʻshimcha shartnoma; кириллица: ўқғҳ ЎҚҒҲ"

SENTENCES = (
    "Сообщаем, что поставка оборудования по заявке будет выполнена в согласованный срок силами нашей бригады.",
    "Перед отгрузкой просим подтвердить готовность площадки к приёмке и назначить ответственного представителя.",
    "Все позиции проходят входной контроль, сертификаты соответствия передаются вместе с товаром.",
    "Монтаж выполняется по проекту, согласованному с вашей технической службой, с соблюдением норм безопасности.",
    "При изменении графика работ мы уведомим вас не позднее чем за три рабочих дня письмом или по телефону.",
    "Оплата производится в порядке, установленном договором, на основании выставленного счёта и акта.",
)


def text(value: str, *marks: str) -> Node:
    node: Node = {"type": "text", "text": value}
    if marks:
        node["marks"] = [{"type": m} for m in marks]
    return node


def var(code: str) -> Node:
    return {"type": "variable", "attrs": {"code": code}}


def para(*content: Node | str, align: str | None = None) -> Node:
    node: Node = {"type": "paragraph", "content": [text(c) if isinstance(c, str) else c for c in content]}
    if align:
        node["attrs"] = {"textAlign": align}
    return node


def heading(level: int, value: str) -> Node:
    return {"type": "heading", "attrs": {"level": level}, "content": [text(value)]}


def cell(value: str, *, header: bool = False, numeric: bool = False, align: str | None = None) -> Node:
    attrs: dict[str, Any] = {}
    if numeric:
        attrs["numeric"] = True
    if align:
        attrs["align"] = align
    node: Node = {"type": "tableHeader" if header else "tableCell", "content": [para(value)]}
    if attrs:
        node["attrs"] = attrs
    return node


def row(*cells: Node, emphasis: bool = False) -> Node:
    node: Node = {"type": "tableRow", "content": list(cells)}
    if emphasis:
        node["attrs"] = {"emphasis": True}
    return node


def signature(*parties: dict[str, Any], stamp: bool = True) -> Node:
    return {"type": "signature", "attrs": {"parties": list(parties), "stamp": stamp}}


def body(content: list[Node], *, lang: str = "ru", **page: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"version": 1, "lang": lang, "doc": {"type": "doc", "content": content}}
    if page:
        out["page"] = page
    return out


DIRECTOR = {"position": {"var": "company.director_position"}, "name": {"var": "company.director"}}
VALUES: dict[str, Value] = {
    "company.director": "А. А. Демонстрационный",
    "company.director_position": "Директор",
    "company.name": "ООО «Демо Рельс Сервис»",
    "counterparty.name": "ООО «Пример Логистик»",
    "counterparty.director": "Б. Б. Примеров",
    "counterparty.director_position": "Генеральный директор",
    "contract.number": "Д-15/26",
    "contract.date": date(2026, 10, 1),
    "invoice.total": Money(Decimal("152340000.00"), "UZS"),
    "invoice.due_date": date(2026, 11, 10),
}
LETTER_META = DocumentMeta(
    number="ИСХ-015/26",
    date=date(2026, 10, 28),
    addressee=("Генеральному директору", "ООО «Пример Логистик»", "Б. Б. Примерову"),
    reply_to="№ 112 от 20.10.2026",
    executor="Исполнитель А. Б. Петрова, +998 00 000-00-01",
)


def letter_short() -> dict[str, Any]:
    """Письмо из пяти строк — одна страница без «Стр. 1 из 1»."""
    return body(
        [
            para("Уважаемый Бахтиёр Бахтиярович!"),
            para("Подтверждаем получение вашего письма и готовность к поставке по заявке ", var("deal.number"), "."),
            para(SENTENCES[1]),
            para("Срок поставки — до ", var("invoice.due_date")),
            para("С уважением,"),
            signature(DIRECTOR),
        ]
    )


def letter_paragraphs(count: int) -> dict[str, Any]:
    """Письмо из `count` абзацев по три предложения (подбор «1,2 страницы» и «осмысленные 2»)."""
    content = [para("Уважаемый Бахтиёр Бахтиярович!")]
    for i in range(count):
        content.append(para(f"{i + 1}. " + " ".join(SENTENCES[(i + k) % len(SENTENCES)] for k in range(3))))
    content += [para("С уважением,"), signature(DIRECTOR)]
    return body(content)


def letter_uz() -> dict[str, Any]:
    return body(
        [
            para("Hurmatli Baxtiyor Baxtiyorovich!"),
            para(
                "Sizning xatingizni olganimizni va ",
                var("deal.number"),
                " buyurtmasi boʻyicha yetkazib berishga tayyorligimizni tasdiqlaymiz.",
            ),
            para(UZ_TEXT),
            para("Hurmat bilan,"),
            signature(DIRECTOR),
        ],
        lang="uz",
    )


CONTRACT_SECTIONS = (
    "Предмет договора",
    "Цена и порядок расчётов",
    "Сроки и порядок поставки",
    "Приёмка товара",
    "Качество и гарантии",
    "Ответственность сторон",
    "Форс-мажор",
    "Разрешение споров",
    "Срок действия договора",
)


def contract() -> dict[str, Any]:
    """Договор поставки на три страницы: статьи, спецификация блоком, реквизиты и подписи."""
    content: list[Node] = [
        para(
            var("company.name"),
            ", именуемое в дальнейшем «Поставщик», в лице ",
            var("company.director_position"),
            " ",
            var("company.director"),
            ", с одной стороны, и ",
            var("counterparty.name"),
            ", именуемое в дальнейшем «Покупатель», с другой стороны, заключили настоящий договор о нижеследующем.",
            align="justify",
        )
    ]
    for n, title in enumerate(CONTRACT_SECTIONS, start=1):
        content.append(heading(2, f"{n}. {title}"))
        for k in range(1, 4):
            sentence = " ".join(SENTENCES[(n + k + j) % len(SENTENCES)] for j in range(2))
            content.append(para(f"{n}.{k}. {sentence}", align="justify"))
    content += [
        {"type": "block", "attrs": {"code": "doc.spec_table", "locked": True, "required": True}},
        {"type": "block", "attrs": {"code": "doc.totals", "locked": True, "required": True}},
        heading(2, "10. Реквизиты и подписи сторон"),
        signature(
            {"role": "Поставщик", **DIRECTOR},
            {
                "role": "Покупатель",
                "position": {"var": "counterparty.director_position"},
                "name": {"var": "counterparty.director"},
            },
        ),
    ]
    return body(content)


def items_table(count: int, *, landscape: bool = False) -> list[Node]:
    """Таблица позиций (данные блока doc.items_table / doc.spec_table): шапка повторяется на каждой странице."""
    if landscape:
        head: tuple[str, ...] = (
            "№",
            "Наименование",
            "Код ТН ВЭД",
            "Производитель",
            "Ед.",
            "Кол-во",
            "Цена",
            "Сумма",
            "Срок",
        )
        widths = [4, 30, 11, 15, 5, 7, 10, 11, 7]
    else:
        head = ("№", "Наименование", "Ед.", "Кол-во", "Цена", "Сумма")
        widths = [5, 49, 7, 9, 14, 16]
    numeric = {"Кол-во", "Цена", "Сумма"}
    rows = [row(*(cell(h, header=True, numeric=h in numeric) for h in head))]
    for i in range(1, count + 1):
        qty = (i % 7) + 1
        price = Decimal(125000 + i * 3150)
        cells = {
            "№": str(i),
            "Наименование": f"Позиция {i}: комплект крепежа рельсового скрепления КБ-{65 + i % 5}, оцинкованный",
            "Код ТН ВЭД": f"7302{i:06d}",
            "Производитель": "АО «Демо Металл»",
            "Ед.": "шт",
            "Кол-во": str(qty),
            "Цена": f"{price:,.2f}".replace(",", " "),
            "Сумма": f"{price * qty:,.2f}".replace(",", " "),
            "Срок": "30 дн.",
        }
        rows.append(row(*(cell(cells[h], numeric=h in numeric) for h in head)))
    return [{"type": "table", "attrs": {"columnWidths": widths, "variant": "grid"}, "content": rows}]


def totals(amount_words: str) -> list[Node]:
    return [
        {
            "type": "table",
            "attrs": {"columnWidths": [60, 40], "variant": "totals"},
            "content": [
                row(cell("Итого без НДС"), cell("136 017 857,14 сум", numeric=True)),
                row(cell("НДС 12 %"), cell("16 322 142,86 сум", numeric=True)),
                row(cell("Итого к оплате"), cell("152 340 000,00 сум", numeric=True), emphasis=True),
            ],
        },
        para(text("Сумма прописью: ", "bold"), amount_words),
    ]


def payment_requisites() -> list[Node]:
    return [
        heading(3, "Платёжные реквизиты"),
        {
            "type": "table",
            "attrs": {"columnWidths": [30, 70], "variant": "plain"},
            "content": [
                row(cell("Получатель"), cell("ООО «Демо Рельс Сервис», ИНН 000 000 000")),
                row(cell("Банк"), cell("АКБ «Демобанк», МФО 00000")),
                row(cell("Расчётный счёт"), cell("0000 0000 0000 0000 0000")),
            ],
        },
    ]


def invoice() -> dict[str, Any]:
    return body(
        [
            para(
                "Покупатель: ",
                var("counterparty.name"),
                ". Основание: договор № ",
                var("contract.number"),
                " от ",
                var("contract.date"),
            ),
            {"type": "block", "attrs": {"code": "doc.items_table", "locked": True, "required": True}},
            {"type": "block", "attrs": {"code": "doc.totals", "locked": True, "required": True}},
            {"type": "block", "attrs": {"code": "doc.payment_requisites", "locked": True, "required": True}},
            para("Оплатить до ", var("invoice.due_date")),
            signature({"role": "Поставщик", **DIRECTOR}),
        ]
    )


def specification() -> dict[str, Any]:
    return body(
        [
            para("Приложение № 1 к договору № ", var("contract.number"), " от ", var("contract.date")),
            {"type": "block", "attrs": {"code": "doc.spec_table", "locked": True}},
            signature(
                {"role": "Поставщик", **DIRECTOR},
                {
                    "role": "Покупатель",
                    "position": {"var": "counterparty.director_position"},
                    "name": {"var": "counterparty.director"},
                },
            ),
        ],
        orientation="landscape",
    )
