import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NBSP } from "../lib/money";
import { renderUi } from "../../test/renderUi";
import { CounterCard, CounterGrid } from "./CounterCard";

describe("CounterCard", () => {
  it("вся карточка — ссылка с подписью, числом и источником", () => {
    renderUi(
      <CounterCard
        label="Входящие без резолюции"
        value={1}
        source="EDS · Входящие"
        to="/eds/inbox"
      />,
    );
    const link = screen.getByRole("link", { name: /Входящие без резолюции/ });
    expect(link).toHaveAttribute("href", "/eds/inbox");
    expect(link).toHaveTextContent("Входящие без резолюции");
    expect(link).toHaveTextContent("1");
    expect(link).toHaveTextContent("EDS · Входящие");
  });

  it("число с неразрывными пробелами и tabular-nums; источник необязателен", () => {
    renderUi(<CounterCard label="Проекты" value={12040} to="/eds/projects" />);
    expect(document.querySelector(".pf-counter-value")?.textContent).toBe(`12${NBSP}040`);
    expect(document.querySelector(".pf-counter-source")).toBeNull();
  });

  it("сетка собирает карточки", () => {
    renderUi(
      <CounterGrid>
        <CounterCard label="А" value={1} to="/a" />
        <CounterCard label="Б" value="2" to="/b" />
      </CounterGrid>,
    );
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });
});
