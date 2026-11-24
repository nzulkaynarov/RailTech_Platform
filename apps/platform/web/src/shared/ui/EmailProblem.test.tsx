import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { EmailProblem } from "./EmailProblem";

describe("EmailProblem", () => {
  it("строка «Письма на этот адрес не доходят: причина · дата»", () => {
    renderUi(<EmailProblem problem={{ reason: "domain_not_found", at: "2026-11-24T10:15:00Z" }} />);
    expect(
      screen.getByText(
        /Письма на этот адрес не доходят: такого почтового домена нет · 24\.11\.2026/,
      ),
    ).toBeInTheDocument();
  });

  it("неизвестная причина — общая формулировка, а не ключ перевода", () => {
    renderUi(<EmailProblem problem={{ reason: "other", at: "2026-11-24T10:15:00Z" }} />);
    expect(screen.getByText(/почтовый сервер вернул письмо/)).toBeInTheDocument();
    expect(screen.queryByText(/emailProblem/)).toBeNull();
  });

  it("нет проблемы — ничего не рисует", () => {
    renderUi(<EmailProblem problem={null} />);
    expect(screen.queryByRole("note")).toBeNull();
  });
});
