import { describe, expect, it } from "vitest";

import { type Block, bodyLang, bodyText, fromBody, isBlank, toBody } from "./bodyModel";

const BLOCKS: Block[] = [
  { id: "1", kind: "paragraph", text: "Уважаемый Алишер Алиевич!\nСообщаем следующее." },
  { id: "2", kind: "bullet", items: ["декларация", "  ", "реестр"] },
  { id: "3", kind: "ordered", items: ["первое"] },
  {
    id: "4",
    kind: "table",
    rows: [
      ["Счёт", "Сумма"],
      ["№ 118", ""],
      ["", ""],
    ],
  },
  { id: "5", kind: "paragraph", text: "   " },
];

describe("bodyModel", () => {
  it("блоки → тело контракта: абзац с переводом строки, списки без пустых пунктов, таблица с шапкой; пустое отброшено", () => {
    const body = toBody(BLOCKS, "ru");
    expect(body.version).toBe(1);
    expect(body.lang).toBe("ru");
    expect(body.doc).toEqual({
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "Уважаемый Алишер Алиевич!" },
            { type: "hardBreak" },
            { type: "text", text: "Сообщаем следующее." },
          ],
        },
        {
          type: "bulletList",
          content: [
            {
              type: "listItem",
              content: [{ type: "paragraph", content: [{ type: "text", text: "декларация" }] }],
            },
            {
              type: "listItem",
              content: [{ type: "paragraph", content: [{ type: "text", text: "реестр" }] }],
            },
          ],
        },
        {
          type: "orderedList",
          content: [
            {
              type: "listItem",
              content: [{ type: "paragraph", content: [{ type: "text", text: "первое" }] }],
            },
          ],
        },
        {
          type: "table",
          attrs: { variant: "grid" },
          content: [
            {
              type: "tableRow",
              content: [
                {
                  type: "tableHeader",
                  content: [{ type: "paragraph", content: [{ type: "text", text: "Счёт" }] }],
                },
                {
                  type: "tableHeader",
                  content: [{ type: "paragraph", content: [{ type: "text", text: "Сумма" }] }],
                },
              ],
            },
            {
              type: "tableRow",
              content: [
                {
                  type: "tableCell",
                  content: [{ type: "paragraph", content: [{ type: "text", text: "№ 118" }] }],
                },
                // пустая ячейка — абзац без текста (в схеме текст не короче 1 знака)
                { type: "tableCell", content: [{ type: "paragraph" }] },
              ],
            },
          ],
        },
      ],
    });
  });

  it("тело → блоки (продолжить черновик) и обратно — то же тело", () => {
    const body = toBody(BLOCKS, "uz");
    const back = fromBody(body);
    expect(back.map((b) => b.kind)).toEqual(["paragraph", "bullet", "ordered", "table"]);
    expect(toBody(back, "uz")).toEqual(body);
  });

  it("плоский текст: абзацы через пустую строку, пункты с «•» и номером, ячейки через « | »", () => {
    expect(bodyText(toBody(BLOCKS, "ru"))).toBe(
      "Уважаемый Алишер Алиевич!\nСообщаем следующее.\n\n• декларация\n• реестр\n\n1. первое\n\nСчёт | Сумма\n№ 118 | ",
    );
  });

  it("пустое тело и язык документа по языку интерфейса", () => {
    expect(isBlank([{ id: "x", kind: "paragraph", text: " " }])).toBe(true);
    expect(isBlank(BLOCKS)).toBe(false);
    expect(fromBody(null)).toHaveLength(1);
    expect(bodyLang("uz-Latn")).toBe("uz");
    expect(bodyLang("en")).toBe("en");
    expect(bodyLang("de")).toBe("ru");
  });
});
