import { describe, expect, it } from "vitest";

import {
  type BodyNode,
  bodyLang,
  bodyText,
  emptyDoc,
  fromBody,
  isBlank,
  normalizeDoc,
  paragraphOf,
  toBody,
} from "./bodyModel";

const text = (value: string, marks?: BodyNode["marks"]): BodyNode => ({
  type: "text",
  text: value,
  ...(marks ? { marks } : {}),
});
const p = (...content: BodyNode[]): BodyNode => ({ type: "paragraph", content });

// Так отдаёт документ редактор Tiptap: лишние атрибуты, пустые абзацы, метки, которых нет в схеме.
const EDITOR_DOC: BodyNode = {
  type: "doc",
  content: [
    { type: "paragraph" },
    { type: "heading", attrs: { level: 2, textAlign: null }, content: [text("Сведения")] },
    {
      type: "paragraph",
      attrs: { textAlign: null },
      content: [
        text("Уважаемый "),
        text("Алишер Алиевич", [{ type: "bold" }, { type: "strike" }]),
        { type: "hardBreak" },
        text("сайт", [{ type: "link", attrs: { href: "https://example.uz", target: "_blank" } }]),
        text(" и ", [{ type: "link", attrs: { href: "javascript:alert(1)" } }]),
      ],
    },
    {
      type: "orderedList",
      attrs: { start: 1, type: null },
      content: [
        { type: "listItem", content: [p(text("первое"))] },
        { type: "listItem", content: [{ type: "paragraph" }] },
      ],
    },
    {
      type: "table",
      content: [
        {
          type: "tableRow",
          content: [
            {
              type: "tableHeader",
              attrs: { colspan: 1, rowspan: 1, colwidth: null },
              content: [p(text("Счёт"))],
            },
            {
              type: "tableHeader",
              attrs: { colspan: 2, rowspan: 1, colwidth: null },
              content: [p(text("Сумма"))],
            },
          ],
        },
        {
          type: "tableRow",
          content: [{ type: "tableCell", attrs: { colspan: 1 }, content: [{ type: "paragraph" }] }],
        },
      ],
    },
    { type: "blockquote", content: [p(text("цитата"))] },
    { type: "paragraph" },
  ],
};

describe("bodyModel: дерево редактора → тело контракта", () => {
  it("лишние атрибуты и метки отброшены, ссылка только с допустимой схемой, пустые края убраны", () => {
    expect(normalizeDoc(EDITOR_DOC)).toEqual({
      type: "doc",
      content: [
        { type: "heading", attrs: { level: 2 }, content: [text("Сведения")] },
        p(
          text("Уважаемый "),
          text("Алишер Алиевич", [{ type: "bold" }]),
          { type: "hardBreak" },
          text("сайт", [{ type: "link", attrs: { href: "https://example.uz" } }]),
          text(" и "),
        ),
        { type: "orderedList", content: [{ type: "listItem", content: [p(text("первое"))] }] },
        {
          type: "table",
          attrs: { variant: "grid" },
          content: [
            {
              type: "tableRow",
              content: [
                { type: "tableHeader", content: [p(text("Счёт"))] },
                { type: "tableHeader", attrs: { colspan: 2 }, content: [p(text("Сумма"))] },
              ],
            },
            {
              type: "tableRow",
              content: [{ type: "tableCell", content: [{ type: "paragraph" }] }],
            },
          ],
        },
        // незнакомый узел — абзац с его текстом
        p(text("цитата")),
      ],
    });
  });

  it("тело → редактор (продолжить черновик) и обратно — то же тело", () => {
    const body = toBody(EDITOR_DOC, "uz");
    expect(toBody(fromBody(body), "uz")).toEqual(body);
    expect(body.lang).toBe("uz");
  });

  it("плоский текст: заголовок, абзац, пункты с номером, ячейки через « | »", () => {
    expect(bodyText(toBody(EDITOR_DOC, "ru"))).toBe(
      "Сведения\n\nУважаемый Алишер Алиевич\nсайт и \n\n1. первое\n\nСчёт | Сумма\n\n\nцитата",
    );
  });

  it("пустое тело, абзац из текста и язык документа", () => {
    expect(isBlank(emptyDoc())).toBe(true);
    expect(isBlank({ type: "doc", content: [p(text(" "))] })).toBe(true);
    expect(isBlank(EDITOR_DOC)).toBe(false);
    expect(fromBody(null)).toEqual(emptyDoc());
    expect(paragraphOf("а\nб")).toEqual(p(text("а"), { type: "hardBreak" }, text("б")));
    expect(bodyLang("uz-Latn")).toBe("uz");
    expect(bodyLang("de")).toBe("ru");
  });
});
