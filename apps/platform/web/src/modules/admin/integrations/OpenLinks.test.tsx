import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailLinks, modelProviderLinks, offsiteLinks, telegramLinks } from "./serviceLinks";
import { panelEl, renderAt, signIn, setupIntegrationsTests } from "./testkit";

setupIntegrationsTests();

const ADMIN = "admin@demo.example";
const DIRECTOR = "director@demo.example";

async function openPanel(card: string, email = ADMIN): Promise<HTMLElement> {
  signIn(email);
  renderAt(`/admin/integrations?card=${card}&panel=open`);
  return panelEl();
}

describe("справочник внешних кабинетов (OPS-CONSOLE)", () => {
  it("почта — по домену SMTP, неизвестный сервер без ссылок", () => {
    expect(mailLinks("smtp.yandex.ru").map((l) => l.href)).toEqual([
      "https://admin.yandex.ru/",
      "https://mail.yandex.ru/",
    ]);
    expect(mailLinks("SMTP.Gmail.com.")[0]?.href).toBe("https://admin.google.com/");
    expect(mailLinks("smtp.notyandex.ru")).toEqual([]);
    expect(mailLinks("smtp.demo.example")).toEqual([]);
  });

  it("модели — консоль по типу ключа, без повторов и без неизвестных", () => {
    expect(modelProviderLinks(["anthropic", "openai", "anthropic", null, "local-llm"])).toEqual([
      { label: "models.anthropic", href: "https://console.anthropic.com/" },
      { label: "models.openai", href: "https://platform.openai.com/" },
    ]);
  });

  it("бот — BotFather всегда, сам бот только с правильным именем", () => {
    expect(telegramLinks("@demo_railtech_bot").map((l) => l.href)).toEqual([
      "https://t.me/BotFather",
      "https://t.me/demo_railtech_bot",
    ]);
    expect(telegramLinks("bad name/../x").map((l) => l.href)).toEqual(["https://t.me/BotFather"]);
  });

  it("внешняя копия — папка Яндекс Диска или Google Диска", () => {
    const base = { folder_path: "", default_folder_path: "RailTech-backups/prod", folder_id: "" };
    expect(offsiteLinks({ ...base, provider: "yandex" })[0]?.href).toBe(
      "https://disk.yandex.ru/client/disk/RailTech-backups/prod",
    );
    expect(
      offsiteLinks({ ...base, provider: "gdrive", folder_id: "1AbCdEfGhIjKlMnOp" })[0]?.href,
    ).toBe("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp");
    expect(offsiteLinks({ ...base, provider: "gdrive" })).toEqual([]);
  });
});

describe("карточки: «Открыть» и «Открыть консоль»", () => {
  it("администратор видит консоль шлюза моделей и консоли провайдеров в новой вкладке", async () => {
    const side = await openPanel("models");
    const consoleLink = await within(side).findByRole("link", {
      name: "Открыть консоль «шлюз моделей» в новой вкладке",
    });
    expect(consoleLink).toHaveAttribute("href", "/console/litellm/ui/");
    expect(consoleLink).toHaveAttribute("target", "_blank");
    const provider = within(side).getByRole("link", {
      name: "Консоль Anthropic — откроется в новой вкладке",
    });
    expect(provider).toHaveAttribute("href", "https://console.anthropic.com/");
    expect(provider).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("администратор видит панель базы в карточке ERP", async () => {
    const side = await openPanel("erp");
    expect(
      await within(side).findByRole("link", {
        name: "Открыть консоль «панель базы» в новой вкладке",
      }),
    ).toHaveAttribute("href", "/console/erp/admin/");
  });

  it("директор — внешние кабинеты есть, служебных консолей нет", async () => {
    const side = await openPanel("models", DIRECTOR);
    expect(
      await within(side).findByRole("link", {
        name: "Консоль Anthropic — откроется в новой вкладке",
      }),
    ).toBeVisible();
    expect(within(side).queryByRole("link", { name: /Открыть консоль/ })).toBeNull();
    screen.getByRole("heading", { level: 1, name: "Подключения" });
  });

  it("бот: BotFather и сам бот", async () => {
    const side = await openPanel("telegram");
    expect(
      await within(side).findByRole("link", { name: "Бот в Telegram — откроется в новой вкладке" }),
    ).toHaveAttribute("href", "https://t.me/demo_railtech_bot");
    expect(
      within(side).getByRole("link", { name: "BotFather — откроется в новой вкладке" }),
    ).toHaveAttribute("href", "https://t.me/BotFather");
  });

  it("хранилище: папка внешней копии на Яндекс Диске", async () => {
    const side = await openPanel("storage");
    expect(
      await within(side).findByRole("link", {
        name: "Папка на Яндекс Диске — откроется в новой вкладке",
      }),
    ).toHaveAttribute("href", "https://disk.yandex.ru/client/disk/RailTech-backups/prod");
  });
});
