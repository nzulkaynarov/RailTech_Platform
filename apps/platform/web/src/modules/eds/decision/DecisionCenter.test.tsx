import { screen, waitFor } from "@testing-library/react";
import { useLocation } from "react-router";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../../test/renderUi";
import { DecisionCenter } from "./DecisionCenter";

function Search() {
  return <output data-testid="search">{useLocation().search}</output>;
}

function renderAt(route: string) {
  renderUi(
    <>
      <DecisionCenter legacyTab="agree" legacySheet="agree" label="Согласование">
        <button type="button">Согласовать</button>
      </DecisionCenter>
      <Search />
    </>,
    { route },
  );
}

describe("DecisionCenter", () => {
  it("форма решения — блок в центре, без вкладки окна", () => {
    renderAt("/eds/approvals/1");
    expect(
      screen.getByRole("region", { name: "Согласование" }).querySelector("button"),
    ).not.toBeNull();
  });

  it("старая ссылка ?panel=open&tab=agree попадает в блок решения и снимает параметры окна", async () => {
    renderAt("/eds/approvals/1?panel=open&tab=agree");
    await waitFor(() => {
      expect(screen.getByTestId("search")).toHaveTextContent("");
    });
    expect(screen.getByRole("button", { name: "Согласовать" })).toBeInTheDocument();
  });

  it("старый лист телефона ?sheet=agree снимается; чужая вкладка и окно не трогаются", async () => {
    renderAt("/eds/approvals/1?sheet=agree&panel=open&tab=route");
    await waitFor(() => {
      expect(screen.getByTestId("search")).toHaveTextContent("?panel=open&tab=route");
    });
  });
});
