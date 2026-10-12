import { describe, expect, it } from "vitest";

import type { ReplyTemplateOut } from "../api/generated/model";
import { fillTemplate, insertIntoDraft, searchTemplates } from "./replyTemplates";

const text = {
  ru: "Здравствуйте, {name}! Меня зовут {manager}, пришлю КП сегодня.",
  uz: "Assalomu alaykum, {name}! Men {manager}.",
  en: "",
};

describe("fillTemplate", () => {
  it.each([
    ["ru", "Иван", "Елена", "Здравствуйте, Иван! Меня зовут Елена, пришлю КП сегодня."],
    ["uz", "Aziz", "Elena", "Assalomu alaykum, Aziz! Men Elena."],
    // Английского нет — русский текст.
    ["en", "John", "Elena", "Здравствуйте, John! Меня зовут Elena, пришлю КП сегодня."],
    [undefined, "Иван", "Елена", "Здравствуйте, Иван! Меня зовут Елена, пришлю КП сегодня."],
    // Имени нет — без «висячей» запятой.
    ["ru", "", "Елена", "Здравствуйте! Меня зовут Елена, пришлю КП сегодня."],
  ])("%s / %s", (language, name, manager, expected) => {
    expect(fillTemplate(text, { language, name, manager })).toBe(expected);
  });

  it("keeps unknown braces untouched", () => {
    const raw = { ru: "Код {x} для {name}", uz: "", en: "" };
    expect(fillTemplate(raw, { language: "ru", name: "Иван", manager: "" })).toBe(
      "Код {x} для Иван",
    );
  });
});

describe("insertIntoDraft", () => {
  it.each([
    ["", "Шаблон", "Шаблон"],
    ["  ", "Шаблон", "Шаблон"],
    ["Добрый день ", "Шаблон", "Добрый день\nШаблон"],
  ])("%j + %j", (draft, insert, expected) => {
    expect(insertIntoDraft(draft, insert)).toBe(expected);
  });
});

describe("searchTemplates", () => {
  const items = [
    { id: 1, title: "КП сегодня", text, updated_at: "" },
    { id: 2, title: "ИНН", text: { ru: "Уточните ИНН", uz: "STIR", en: "Tax ID" }, updated_at: "" },
  ] as ReplyTemplateOut[];

  it.each([
    ["", [1, 2]],
    ["кп", [1]],
    ["tax", [2]],
    ["нет такого", []],
  ])("%j", (query, ids) => {
    expect(searchTemplates(items, query).map((i) => i.id)).toEqual(ids);
  });
});
