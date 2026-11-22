import { describe, expect, it } from "vitest";

import { humanTextProblems, scanHumanText, visibleText } from "./humanText";

const found = (text: string) => scanHumanText(text).map((f) => `${f.kind}:${f.text}`);

describe("охранник человеческого текста", () => {
  it("ловит сырые ключи и коды событий, даты ISO, суммы без разрядов, «(и)» и «#2»", () => {
    expect(found("Колокольчик: notifications.kindChip.supplier_order")).toEqual([
      "key:notifications.kindChip.supplier_order",
    ]);
    expect(found("file.attached")).toEqual(["key:file.attached"]);
    expect(found("расчёт по заявке #2 до 2026-11-22")).toEqual([
      "iso-date:2026-11-22",
      "internal-number:#2",
    ]);
    expect(found("Сумма 1500000.00")).toEqual(["bare-amount:1500000.00"]);
    expect(found("В заявке 2 строк(и), назначен(а)")).toEqual([
      "plural-hack:к(и)",
      "plural-hack:н(а)",
    ]);
  });

  it("не трогает почту, адреса, имена файлов, номера документов и суммы с разрядами", () => {
    expect(
      found(
        "sales@partner.example · https://platform.railtech.uz/erp · scan.pdf · ВХ-104/26 · ПР-2026-099 · 1 500 000,00 сум · 12.05.2026 · v1.2",
      ),
    ).toEqual([]);
  });

  it("список допустимого снимает ровно названное совпадение в названном файле", () => {
    const text = "дата 2026-11-22 и ещё file.attached";
    const allowed = [{ file: "Some.test", kind: "iso-date" as const, text: "2026-11-22" }];
    expect(humanTextProblems("x/Some.test.tsx", text, new Set(), allowed, [])).toEqual([
      "key: «file.attached»",
    ]);
    expect(humanTextProblems("x/Other.test.tsx", text, new Set(), allowed, [])).toEqual([
      "key: «file.attached»",
      "iso-date: «2026-11-22»",
    ]);
  });

  it("ключ без перевода — нарушение", () => {
    expect(humanTextProblems("a.test.ts", "", new Set(["shell:no.such.key"]), [], [])).toEqual([
      "нет перевода: shell:no.such.key",
    ]);
  });
});

describe("видимый текст экрана", () => {
  it("соседние ячейки не склеиваются, скрытое и стили не читаются", () => {
    document.body.innerHTML =
      "<table><tr><td>860</td><td>12.00</td></tr></table><div hidden>secret.key</div><style>a.b{}</style><p>ok</p>";
    expect(visibleText(document.body)).toBe("860 12.00 ok");
    expect(scanHumanText(visibleText(document.body))).toEqual([]);
    document.body.innerHTML = "";
  });
});
