import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderUi } from "../../test/renderUi";
import { DocNumber } from "./DocNumber";

const original = Object.getOwnPropertyDescriptor(navigator, "clipboard");

function stubClipboard(writeText: ((text: string) => Promise<void>) | undefined) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: writeText ? { writeText } : undefined,
  });
}

afterEach(() => {
  if (original) Object.defineProperty(navigator, "clipboard", original);
  else Reflect.deleteProperty(navigator, "clipboard");
});

describe("DocNumber", () => {
  it("номер и кнопка «Скопировать номер», если есть буфер обмена", () => {
    stubClipboard(vi.fn().mockResolvedValue(undefined));
    renderUi(<DocNumber number="ПР-2026-104" />);
    expect(screen.getByText("ПР-2026-104")).toHaveAttribute("translate", "no");
    expect(screen.getByRole("button", { name: "Скопировать номер ПР-2026-104" })).toBeVisible();
  });

  it("без буфера обмена (http) — только номер, без кнопки", () => {
    stubClipboard(undefined);
    renderUi(<DocNumber number="ПР-2026-104" />);
    expect(screen.getByText("ПР-2026-104")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("с base — ссылка на карточку", () => {
    renderUi(<DocNumber number="ПР-2026-104" base="/eds/documents" copyable={false} />);
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/eds/documents/%D0%9F%D0%A0-2026-104",
    );
  });

  it("копирование: номер в буфере и тост «Номер скопирован»", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    renderUi(<DocNumber number="ПР-2026-104" />);
    fireEvent.click(screen.getByRole("button", { name: "Скопировать номер ПР-2026-104" }));
    expect(writeText).toHaveBeenCalledWith("ПР-2026-104");
    expect(await screen.findByText("Номер скопирован")).toBeInTheDocument();
  });

  it("браузер отказал в доступе — словами, без необработанной ошибки", async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    renderUi(<DocNumber number="ПР-2026-104" />);
    fireEvent.click(screen.getByRole("button", { name: "Скопировать номер ПР-2026-104" }));
    expect(await screen.findByText(/Не удалось скопировать/)).toBeInTheDocument();
  });
});
