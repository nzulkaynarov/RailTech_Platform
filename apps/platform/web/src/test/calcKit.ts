import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect } from "vitest";

import { usePanelsStore } from "../app/shell/panelsStore";
import { resetCalcMock } from "../mocks/erpCalc";
import { endSession } from "../mocks/mockSession";
import i18n from "../shared/i18n";
import { setViewportWidth } from "./viewport";

export { panelEl, renderAt, signIn } from "./botKit";

const missing: string[] = [];

/** Подготовка и уборка теста «Расчёт по заявке»: исходные расчёты мока, ширина окна, русский язык, ни одного пропущенного ключа. */
export function setupCalcTests(width = 1440): void {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    resetCalcMock();
    usePanelsStore.setState({ entries: {} });
    setViewportWidth(width);
    missing.length = 0;
    i18n.options.saveMissing = true;
    i18n.options.missingKeyHandler = (_languages, namespace, key, fallback) => {
      if (fallback !== "") missing.push(`${namespace}:${key}`);
    };
    void i18n.changeLanguage("ru");
  });
  afterEach(() => {
    cleanup();
    endSession();
    i18n.options.saveMissing = false;
    expect(missing, "в словаре нет ключей, которые просит экран").toEqual([]);
  });
}
