import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { DefinitionList } from "./DefinitionList";

describe("DefinitionList", () => {
  it("термин → определение", () => {
    renderUi(
      <DefinitionList
        items={[
          { label: "Клиент", value: "АО «Демо-Транс»" },
          { label: "ИНН", value: "300000001" },
        ]}
      />,
    );
    const terms = document.querySelectorAll("dt");
    const defs = document.querySelectorAll("dd");
    expect(Array.from(terms).map((t) => t.textContent)).toEqual(["Клиент", "ИНН"]);
    expect(Array.from(defs).map((d) => d.textContent)).toEqual(["АО «Демо-Транс»", "300000001"]);
  });

  it("пустое значение — «—» и слово для скринридера", () => {
    renderUi(
      <DefinitionList
        items={[
          { label: "E-mail", value: null },
          { label: "Телефон", value: "" },
        ]}
      />,
    );
    const defs = document.querySelectorAll("dd");
    expect(defs[0]).toHaveTextContent("—не указано");
    expect(defs[0]?.querySelector('[aria-hidden="true"]')).toHaveTextContent("—");
    expect(defs[1]).toHaveTextContent("не указано");
  });

  it("ноль и узел — не пустые значения", () => {
    renderUi(
      <DefinitionList
        items={[
          { label: "Строк", value: 0 },
          { label: "Ссылка", value: <a href="/x">х</a> },
        ]}
      />,
    );
    expect(document.querySelectorAll("dd")[0]).toHaveTextContent("0");
    expect(screen.getByRole("link", { name: "х" })).toBeVisible();
  });
});
