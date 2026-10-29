import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderUi } from "../../test/renderUi";
import { DocNumber } from "./DocNumber";

describe("DocNumber", () => {
  it("рендерит номер документа и кнопку копирования", () => {
    renderUi(<DocNumber number="ПР-2026-104" />);
    expect(screen.getByText("ПР-2026-104")).toBeVisible();
    const copyBtn = screen.getByRole("button", { name: "Скопировать номер ПР-2026-104" });
    expect(copyBtn).toBeVisible();
  });

  it("рендерит ссылку при передаче base", () => {
    renderUi(<DocNumber number="ПР-2026-104" base="/eds/documents" />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/eds/documents/%D0%9F%D0%A0-2026-104");
  });

  it("вызывает navigator.clipboard.writeText по клику на копирование", () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    renderUi(<DocNumber number="ПР-2026-104" />);
    const copyBtn = screen.getByRole("button", { name: "Скопировать номер ПР-2026-104" });
    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledWith("ПР-2026-104");
  });
});
