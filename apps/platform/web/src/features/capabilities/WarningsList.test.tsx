import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { CapabilityWarning } from "../../shared/api/generated/model";
import i18n from "../../shared/i18n";
import { WarningsList } from "./WarningsList";

const names = { quote: { ru: "Коммерческое предложение", uz: "TT", en: "Quote" } };
const warnings: CapabilityWarning[] = [
  {
    code: "only_decider",
    capability: "quote",
    person: { id: "1", name: "Рустам Д.", initials: "РД" },
  },
  { code: "nobody_decides", capability: "quote" },
];

beforeEach(() => {
  void i18n.changeLanguage("ru");
});
afterEach(cleanup);

describe("Предупреждения таблицы", () => {
  it("одна короткая строка со счётом, «Показать» раскрывает список по одному в строке", () => {
    render(<WarningsList warnings={warnings} names={names} />);

    expect(screen.getByText(/1 решение держится на одном человеке/)).toBeVisible();
    expect(screen.queryByRole("listitem")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Показать" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Скрыть" }));
    expect(screen.queryByRole("listitem")).toBeNull();
  });

  it("без предупреждений ничего не показывает", () => {
    const { container } = render(<WarningsList warnings={[]} names={names} />);
    expect(container).toBeEmptyDOMElement();
  });
});
