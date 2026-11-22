import { describe, expect, it } from "vitest";

import { RECORD_TAB_SET } from "../../modules/types";
import {
  effectivePanelTab,
  hasBuiltInTab,
  panelHasContent,
  visiblePanelTabs,
} from "./panelSlotContext";

const tabs = RECORD_TAB_SET.map((t) => t.key);
const none = () => false;

describe("вкладки бокового окна без данных не показываются (ЕД-7)", () => {
  it("видны только занятые страницей вкладки, порядок — как у раздела", () => {
    expect(visiblePanelTabs(tabs, ["history", "facts"], none)).toEqual(["facts", "history"]);
  });

  it("вкладки, которые наполняет сам каркас, видны без страницы", () => {
    const shown = visiblePanelTabs(["today", "notifications", "chat"], [], (tab) =>
      hasBuiltInTab("dashboard", "queue", tab),
    );
    expect(shown).toEqual(["today", "notifications"]);
    expect(hasBuiltInTab("eds", "projects", "today")).toBe(false);
  });

  it("никто ничего не занял — остаётся одна первая вкладка, окно не бывает без вкладок", () => {
    expect(visiblePanelTabs(tabs, [], none)).toEqual(["facts"]);
  });

  it("выбранная вкладка исчезла — активна первая видимая; есть — остаётся выбранная", () => {
    expect(effectivePanelTab("history", ["facts"])).toBe("facts");
    expect(effectivePanelTab("history", ["facts", "history"])).toBe("history");
  });

  it("форма поверх держит «Карточку» видимой, даже если набора раздела в ней нет", () => {
    expect(tabs).not.toContain("card");
    expect(visiblePanelTabs(tabs, ["facts", "card"], none, true)).toEqual(["card", "facts"]);
    expect(visiblePanelTabs(tabs, [], none, true)).toEqual(["card"]);
    expect(effectivePanelTab("card", visiblePanelTabs(tabs, ["facts"], none, true))).toBe("card");
    // без формы вкладки «Карточка» в окне набора нет
    expect(visiblePanelTabs(tabs, ["facts"], none, false)).toEqual(["facts"]);
  });

  it("экран ничего не положил в окно — содержимого нет (окно само не открывается)", () => {
    expect(panelHasContent(tabs, [], none)).toBe(false);
    expect(panelHasContent(tabs, ["facts"], none)).toBe(true);
    expect(panelHasContent(["today"], [], (t) => hasBuiltInTab("dashboard", "queue", t))).toBe(
      true,
    );
  });
});
