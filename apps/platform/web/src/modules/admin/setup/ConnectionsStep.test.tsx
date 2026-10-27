import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import i18n from "../../../shared/i18n";
import { ConnectionsStep } from "./ConnectionsStep";

describe("мастер первого запуска: шаги чек-листа", () => {
  it("шаг без проверки — «Не проверено — нажмите «Проверить»», а не «Готово» (O-4)", async () => {
    await i18n.changeLanguage("ru");
    render(
      <MemoryRouter>
        <ConnectionsStep
          steps={[
            { key: "bot", state: "done" },
            { key: "models", state: "unknown" },
            { key: "mail", state: "todo" },
          ]}
        />
      </MemoryRouter>,
    );

    const items = screen.getAllByRole("listitem");
    const models = items.find((li) => li.getAttribute("data-step") === "models");
    if (!models) throw new Error("нет шага «Модели ИИ»");
    expect(within(models).getByText("Не проверено — нажмите «Проверить»")).toBeVisible();
    expect(within(models).queryByText("Готово")).toBeNull();
    const bot = items.find((li) => li.getAttribute("data-step") === "bot");
    expect(within(bot as HTMLElement).getByText("Готово")).toBeVisible();
  });
});
