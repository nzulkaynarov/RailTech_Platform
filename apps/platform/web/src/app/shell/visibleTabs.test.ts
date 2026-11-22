import { describe, expect, it } from "vitest";

import { RECORD_TAB_SET } from "../../modules/types";
import { effectivePanelTab, hasBuiltInTab, visiblePanelTabs } from "./panelSlotContext";

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
});
