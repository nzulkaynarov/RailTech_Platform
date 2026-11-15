import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NameCode } from "./NameCode";

describe("NameCode", () => {
  it("shows the code under the name, muted and announced with its label", () => {
    const { container } = render(
      <NameCode name="Реле защиты" code="RT-0002" codeLabel="Артикул" />,
    );
    expect(screen.getByText("Реле защиты")).toBeInTheDocument();
    const code = screen.getByText("RT-0002");
    expect(code).toHaveClass("pf-code", "pf-code--quiet");
    expect(code).toHaveAttribute("translate", "no");
    expect(container).toHaveTextContent("Реле защитыАртикул: RT-0002");
  });

  it("renders only the name when there is no code", () => {
    const { container } = render(<NameCode name="Письмо банка" code={null} />);
    expect(container).toHaveTextContent(/^Письмо банка$/);
    expect(container.querySelector(".pf-code")).toBeNull();
  });
});
