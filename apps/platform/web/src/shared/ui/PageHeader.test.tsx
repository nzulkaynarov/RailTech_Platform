import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { PageHeader } from "./PageHeader";
import { SoonButton } from "./SoonButton";

describe("PageHeader", () => {
  it("h1 20/600 с подзаголовком и действием", () => {
    renderUi(
      <PageHeader
        title="Моя очередь"
        subtitle="Директор · четверг"
        extra={<button type="button">Действие</button>}
      />,
    );
    const heading = screen.getByRole("heading", { level: 1, name: "Моя очередь" });
    expect(heading).toHaveStyle({ fontSize: "20px", fontWeight: "600", lineHeight: "28px" });
    expect(screen.getByText("Директор · четверг")).toBeVisible();
    expect(screen.getByRole("button", { name: "Действие" })).toBeVisible();
  });
});

describe("SoonButton", () => {
  it("неактивна, имя несёт пояснение", () => {
    renderUi(<SoonButton>Создать заявку</SoonButton>);
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleName("Создать заявку. Появится в фазе P2");
  });
});
