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
            { key: "bot", state: "done", to: "/admin/setup?step=bot&panel=open" },
            { key: "models", state: "unknown", to: "/admin/setup?step=models&panel=open" },
            { key: "mail", state: "todo", to: "/admin/setup?step=mail&panel=open" },
            { key: "signing", state: "todo", to: "/admin/signing" },
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
    // СЦ-3: права подписи — строка с переходом на «Права подписи»
    const signing = items.find((li) => li.getAttribute("data-step") === "signing");
    expect(within(signing as HTMLElement).getByText("Права подписи")).toBeVisible();
    expect(within(signing as HTMLElement).getByRole("link", { name: "Выдать" })).toHaveAttribute(
      "href",
      "/admin/signing",
    );
  });
});
