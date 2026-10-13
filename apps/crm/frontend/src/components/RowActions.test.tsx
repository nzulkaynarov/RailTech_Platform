import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActionsTitle, RowActions } from "./RowActions";

describe("RowActions", () => {
  it("is a named menu button and runs the chosen action", async () => {
    const reingest = vi.fn();
    render(
      <RowActions
        label="Действия с документом «Прайс»"
        actions={[{ key: "reingest", label: "Переиндексировать", onClick: reingest }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Действия с документом «Прайс»" }));
    fireEvent.click(await screen.findByText("Переиндексировать"));
    expect(reingest).toHaveBeenCalledOnce();
  });

  it("renders nothing without actions", () => {
    const { container } = render(<RowActions label="x" actions={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("actions column has a screen-reader title", () => {
    render(<ActionsTitle />);
    expect(screen.getByText("Действия")).toHaveClass("sr-only");
  });
});
