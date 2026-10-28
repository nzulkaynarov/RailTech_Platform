import { describe, expect, it } from "vitest";

import { isActionable } from "./bridge";
import { objectLink } from "./objectLinks";

const seg = encodeURIComponent;
const UUID = "5f0c7a52-3b1e-4c53-9d0a-1c6a1f0e2b77";

describe("переходы: адрес и вкладка бокового окна по виду объекта (D1-6)", () => {
  it.each([
    // письмо -> «Входящие», вкладка «Резолюция»
    [
      "письмо: полный адрес BFF не меняется",
      {
        kind: "letter",
        number: "ВХ-104/26",
        path: `/eds/inbox/${seg("ВХ-104/26")}?panel=open&tab=resolution`,
      },
      `/eds/inbox/${seg("ВХ-104/26")}?panel=open&tab=resolution`,
    ],
    [
      "письмо: адрес без окна достраивается до вкладки «Резолюция»",
      { kind: "letter", number: "ВХ-104/26", path: `/eds/inbox/${seg("ВХ-104/26")}` },
      `/eds/inbox/${seg("ВХ-104/26")}?panel=open&tab=resolution`,
    ],
    [
      "письмо: адрес по id (UUID) тоже открывает вкладку",
      { kind: "letter", number: "ВХ-104/26", path: `/eds/inbox/${UUID}` },
      `/eds/inbox/${UUID}?panel=open&tab=resolution`,
    ],
    [
      "письмо: BFF прислал список — карточка строится из бизнес-номера",
      { kind: "letter", number: "ВХ-104/26", path: "/eds/inbox" },
      `/eds/inbox/${seg("ВХ-104/26")}?panel=open&tab=resolution`,
    ],
    // КП на одобрении -> «Черновик», вкладка «Одобрение»
    [
      "КП: черновик открывается на вкладке «Одобрение»",
      { kind: "quote", number: "КП-2026/118", path: `/eds/drafts/${seg("КП-2026/118")}` },
      `/eds/drafts/${seg("КП-2026/118")}?panel=open&tab=approve`,
    ],
    [
      "КП: вкладка из адреса BFF сохраняется",
      {
        kind: "quote",
        number: "КП-2026/118",
        path: `/eds/drafts/${seg("КП-2026/118")}?panel=open&tab=chat`,
      },
      `/eds/drafts/${seg("КП-2026/118")}?panel=open&tab=chat`,
    ],
    // служебка -> «На согласовании», вкладка «Согласование»
    [
      "служебка: вкладка «Согласование»",
      { kind: "memo", number: "СЗ-2026/031", path: `/eds/approvals/${seg("СЗ-2026/031")}` },
      `/eds/approvals/${seg("СЗ-2026/031")}?panel=open&tab=agree`,
    ],
    [
      "служебка без номера в пути: из номера объекта",
      { kind: "memo", number: "СЗ-2026/031", path: "/eds/approvals?panel=open" },
      `/eds/approvals/${seg("СЗ-2026/031")}?panel=open&tab=agree`,
    ],
  ] as const)("%s", (_name, object, expected) => {
    expect(objectLink(object)).toBe(expected);
  });

  it.each([
    [
      "сообщение клиента (передача) — диалог в «Ждут ответа», номер лида в адресе",
      { kind: "lead", number: "L-2041", path: "/crm/messages?lead=L-2041" },
    ],
    [
      "лид из поиска — карточка в «Все лиды»",
      { kind: "lead", number: "L-2041", path: "/crm/leads?lead=L-2041&panel=open&tab=card" },
    ],
    [
      "свой документ — реестр с карточкой в окне",
      { kind: "memo", number: "СЗ-2026/040", path: `/eds/documents?doc=${UUID}` },
    ],
    [
      "отправленное КП — «Исходящие» без родного экрана: адрес не трогаем",
      {
        kind: "quote",
        number: "КП-2026/118",
        path: `/eds/outbox/${seg("КП-2026/118")}?panel=open&tab=card`,
      },
    ],
    [
      "счёт — раздел без экрана",
      {
        kind: "invoice",
        number: "СЧ-2026/142",
        path: `/eds/payments/${seg("СЧ-2026/142")}?panel=open&tab=payment`,
      },
    ],
    ["адрес не из карты Платформы", { kind: "letter", number: "ВХ-1/26", path: "/somewhere/else" }],
  ] as const)("без правки: %s", (_name, object) => {
    expect(objectLink(object)).toBe(object.path);
  });

  it("раздел «Входящие» не открывает КП из списка: чужой вид объекта адрес не достраивает", () => {
    const object = { kind: "quote", number: "КП-2026/118", path: "/eds/inbox" } as const;
    expect(objectLink(object)).toBe("/eds/inbox");
  });

  it("у письма, КП, служебки, диалога и своих документов есть экран — «Где сделать» им не нужно", () => {
    for (const object of [
      { kind: "letter", number: "ВХ-104/26", path: `/eds/inbox/${seg("ВХ-104/26")}` },
      { kind: "quote", number: "КП-2026/118", path: `/eds/drafts/${seg("КП-2026/118")}` },
      { kind: "memo", number: "СЗ-2026/031", path: `/eds/approvals/${seg("СЗ-2026/031")}` },
      { kind: "lead", number: "L-2041", path: "/crm/messages?lead=L-2041" },
      { kind: "memo", number: "СЗ-2026/040", path: `/eds/documents?doc=${UUID}` },
      { kind: "memo", number: "СЗ-2026/040", path: "/eds/new?type=memo" },
    ] as const) {
      expect(isActionable(objectLink(object)), object.path).toBe(true);
    }
  });

  it("договор, счёт, акт и склад остаются без экрана — остаётся «Где сделать»", () => {
    for (const path of [
      "/eds/projects/%D0%9F%D0%A0-2026-099?panel=open&tab=documents",
      `/eds/payments/${seg("СЧ-2026/142")}`,
      "/erp/stock",
    ]) {
      expect(isActionable(path), path).toBe(false);
    }
  });
});
