import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEMO_WRONG_PASSWORD } from "../../../mocks/fixtures/users";
import { server } from "../../../test/server";
import { panelEl, renderAt, setupIntegrationsTests, signIn } from "./testkit";

setupIntegrationsTests();

const PASSWORD = "demo-pass-1";

function type(label: string | RegExp, value: string, root: HTMLElement = document.body) {
  fireEvent.change(within(root).getByLabelText(label), { target: { value } });
}

function press(root: HTMLElement, name: string) {
  fireEvent.click(within(root).getByRole("button", { name: new RegExp(`(^|loading)${name}$`) }));
}

async function attention(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { level: 2, name: "Требует внимания" });
  const section = heading.closest("section");
  if (!section) throw new Error("нет раздела «Требует внимания»");
  return section;
}

async function groupRow(text: RegExp): Promise<HTMLElement> {
  const section = await attention();
  const row = await waitFor(() => {
    const found = within(section)
      .getAllByRole("listitem")
      .find((li) => li.getAttribute("data-group") && within(li).queryByText(text));
    if (!found) throw new Error("нет строки");
    return found;
  });
  return row;
}

const copied: string[] = [];

beforeEach(() => {
  copied.length = 0;
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: vi.fn((text: string) => {
        copied.push(text);
        return Promise.resolve();
      }),
    },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Требует внимания: одна причина — одна строка", () => {
  it("строка группы: слово состояния, что не работает, «с …», «Кто исправляет», одно главное действие", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations");

    const row = await groupRow(/Ключ OpenAI отклонён/);
    expect(row).toHaveAttribute("data-state", "broken");
    expect(within(row).getByText("Сломано")).toBeVisible();
    expect(
      within(row).getByText(/— не работают: поиск по базе знаний, проверка качества ответов/),
    ).toBeVisible();
    expect(within(row).getByText(/^с 26\.10\.2026, 08:40|^с 26\.10\.2026/)).toBeVisible();
    expect(within(row).getByText("Кто исправляет:")).toBeVisible();
    expect(within(row).getByText(/ключ и оплата — у владельца компании/)).toBeVisible();
    // человеческая подсказка CRM есть, сырого ответа провайдера нет
    expect(within(row).getByText(/введите новый ключ в «Модели ИИ»/)).toBeVisible();
    expect(within(row).queryByText(/invalid_api_key/)).not.toBeInTheDocument();
    // главное действие — первая кнопка, остальные — запасные
    const buttons = within(row).getAllByRole("button");
    expect(buttons[0]).toHaveAccessibleName("Ввести новый ключ: Ключ OpenAI отклонён");
    expect(within(row).getByRole("button", { name: /Написать владельцу/ })).toBeVisible();
    expect(within(row).getByRole("button", { name: /Выключить провайдера/ })).toBeVisible();
  });

  it("«Технические подробности» свёрнуты; раскрытые показывают сырой ответ, «Скопировать для поддержки» кладёт его в буфер", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations");
    const row = await groupRow(/Ключ OpenAI отклонён/);

    const toggle = within(row).getByRole("button", { name: "Технические подробности" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.body.textContent).not.toContain("invalid_api_key");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(row).getByText(/invalid_api_key/)).toBeVisible();

    fireEvent.click(within(row).getByRole("button", { name: "Скопировать для поддержки" }));
    await waitFor(() => {
      expect(copied).toHaveLength(1);
    });
    expect(copied[0]).toContain("OpenAI");
    expect(copied[0]).toContain("invalid_api_key");
    expect(copied[0]).toContain("Сломано");
    expect(await screen.findByText("Скопировано для поддержки")).toBeVisible();
  });

  it("«Написать владельцу»: готовый текст, «Скопировать», ссылки в почту и Telegram — без отправки", async () => {
    signIn("admin@demo.example");
    const sent = vi.fn();
    server.use(
      http.post("*", () => {
        sent();
        return HttpResponse.json({});
      }),
    );
    renderAt("/admin/integrations");
    const row = await groupRow(/Ключ OpenAI отклонён/);

    fireEvent.click(within(row).getByRole("button", { name: /Написать владельцу/ }));
    const box = within(row).getByRole("group", { name: "Готовый текст: владельцу компании" });
    const text = within(box).getByRole("textbox", { name: "Текст сообщения" });
    expect(text).toHaveAttribute("readonly");
    expect((text as HTMLTextAreaElement).value).toContain("Ключ OpenAI отклонён");
    expect((text as HTMLTextAreaElement).value).toContain("новый ключ");

    fireEvent.click(within(box).getByRole("button", { name: "Скопировать" }));
    await waitFor(() => {
      expect(copied).toHaveLength(1);
    });
    expect(copied[0]).toBe((text as HTMLTextAreaElement).value);
    const mail = within(box).getByRole("link", { name: "Открыть в почте" });
    expect(mail.getAttribute("href")).toMatch(/^mailto:\?subject=/);
    const telegram = within(box).getByRole("link", { name: "Открыть в Telegram" });
    expect(telegram.getAttribute("href")).toMatch(/^https:\/\/t\.me\/share\/url/);
    expect(within(box).getByText(/Платформа ничего не отправляет/)).toBeVisible();
    expect(sent).not.toHaveBeenCalled();
  });

  it("«Ввести новый ключ»: форма прямо в строке, один ключ на все роли, ключ не показывается, строка уходит", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations");
    const row = await groupRow(/Ключ OpenAI отклонён/);

    fireEvent.click(within(row).getByRole("button", { name: /Ввести новый ключ/ }));
    const form = await within(row).findByRole("form", { name: "Новый ключ OpenAI" });
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    expect(within(form).getByText(/Поиск по базе знаний, Проверка качества/)).toBeVisible();
    expect(within(form).getByRole("button", { name: "Применить ключ" })).toBeDisabled();

    type("Новый ключ", "demo-provider-key-77qq", form);
    type("Ваш пароль администратора", DEMO_WRONG_PASSWORD, form);
    press(form, "Применить ключ");
    expect(await within(form).findByRole("alert")).toHaveTextContent("Пароль указан неверно.");

    type("Ваш пароль администратора", PASSWORD, form);
    press(form, "Применить ключ");

    await waitFor(() => {
      expect(screen.queryByText(/Ключ OpenAI отклонён/)).not.toBeInTheDocument();
    });
    expect(document.body.textContent).not.toContain("demo-provider-key-77qq");
  });

  it("«Проверить снова» (перебои у почты): сразу проверяет, восстановилось — строка уходит", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations");
    const row = await groupRow(/В очереди 3 письма дольше 15 минут/);
    expect(within(row).getByText("Работает с перебоями")).toBeVisible();

    fireEvent.click(
      within(row).getByRole("button", { name: /Проверить снова: В очереди 3 письма/ }),
    );

    await waitFor(() => {
      expect(screen.queryByText("В очереди 3 письма дольше 15 минут")).not.toBeInTheDocument();
    });
  });

  it("«Выключить провайдера»: форма с паролем и блоком «Что произойдёт»", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations");
    const row = await groupRow(/Ключ OpenAI отклонён/);

    fireEvent.click(within(row).getByRole("button", { name: /Выключить провайдера/ }));

    const form = await within(row).findByRole("form", { name: "Выключить сервис: OpenAI" });
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
  });

  it("директор: видит причину и «Написать владельцу», но не кнопки изменения и проверки", async () => {
    signIn("director@demo.example");
    renderAt("/admin/integrations");
    const row = await groupRow(/Ключ OpenAI отклонён/);

    expect(within(row).getByRole("button", { name: /Написать владельцу/ })).toBeVisible();
    expect(within(row).queryByRole("button", { name: /Ввести новый ключ/ })).toBeNull();
    expect(within(row).queryByRole("button", { name: /Выключить провайдера/ })).toBeNull();
    expect(within(row).queryByRole("button", { name: /Проверить снова/ })).toBeNull();
  });
});

describe("Нестабильно: дребезг без сбоя и писем", () => {
  it("«Нестабильно» — жёлтое слово, «провалов за сутки: N», без «Сломано» и без кнопок письма", async () => {
    signIn("admin@demo.example");
    const unstable = {
      id: "docling:flapping",
      state: "unstable",
      owner: null,
      action: "recheck",
      more_actions: [],
      headline: "Распознавание документов (docling): нестабильная связь, провалов за сутки: 7",
      detail: null,
      affected: [],
      service_keys: ["docling"],
      titles: ["Распознавание документов (docling)"],
      since: "2026-10-26T08:00:00Z",
      technical: [],
      message: null,
      fix_card: null,
      flaps_24h: 7,
    };
    server.use(
      http.get("*/admin/integrations", () =>
        HttpResponse.json({
          checked_at: "2026-10-26T09:12:00Z",
          cards: [],
          attention: [
            {
              id: "group:docling:flapping",
              card: "services",
              severity: "warn",
              kind: "service",
              subject: unstable.headline,
              detail: null,
              group: unstable,
              technical: null,
            },
          ],
        }),
      ),
    );
    renderAt("/admin/integrations");

    const row = await groupRow(/нестабильная связь/);
    expect(row).toHaveAttribute("data-state", "unstable");
    const tag = within(row).getByText("Нестабильно");
    expect(tag.closest("[data-tone]")).toHaveAttribute("data-tone", "gold");
    expect(within(row).getByText("Провалов за сутки: 7")).toBeVisible();
    expect(within(row).queryByText("Сломано")).toBeNull();
    expect(within(row).queryByRole("button", { name: /Написать/ })).toBeNull();
  });
});

describe("Внешние сервисы: состояние словом", () => {
  it("«Ожидаемо на стенде» — серым и без «Требует внимания»; «Не проверено» — с подсказкой «нажмите «Проверить»»", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations?card=services&panel=open");
    const side = await panelEl();

    const docling = (await within(side).findByText("Распознавание документов (docling)")).closest(
      "li",
    );
    if (!docling) throw new Error("нет строки docling");
    const tag = within(docling).getByText("Ожидаемо на стенде");
    expect(tag.closest("[data-tone]")).toHaveAttribute("data-tone", "default");
    expect(within(docling).getByText(/Тестовый стенд: здесь это ожидаемо/)).toBeVisible();

    const erpFiles = within(side).getByText("Файлы ERP (S3)").closest("li");
    if (!erpFiles) throw new Error("нет строки Файлы ERP (S3)");
    expect(within(erpFiles).getByText("Не проверено")).toBeVisible();
    expect(within(erpFiles).getByText("Не проверено — нажмите «Проверить»")).toBeVisible();

    const langfuse = within(side).getByText("Langfuse (журнал работы ИИ)").closest("li");
    if (!langfuse) throw new Error("нет строки Langfuse");
    expect(within(langfuse).getByText("Выключено намеренно")).toBeVisible();

    const section = await attention();
    expect(within(section).queryByText(/Распознавание документов/)).toBeNull();
    expect(within(section).queryByText(/Langfuse/)).toBeNull();
  });

  it("ошибки провайдера у карточки «Модели ИИ» — словами, сырой текст под «Техническими подробностями»", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations?card=models&panel=open");
    const side = await panelEl();

    const rows = await within(side).findAllByText(
      "Роль «Поиск по базе знаний» не отвечает: проверьте ключ и баланс у провайдера.",
    );
    expect(rows.length).toBeGreaterThan(0);
    expect(within(side).queryAllByText("401: ключ отклонён провайдером")).toHaveLength(0);
  });
});

describe("Telegram: индикатор не противоречит строке (O-1)", () => {
  it("токен не задан — «Состояние бота: не работает — токен не задан», а не «Работает»", async () => {
    signIn("admin@demo.example");
    server.use(
      http.get("*/admin/integrations/telegram", () =>
        HttpResponse.json({
          channel_id: null,
          channel_title: null,
          configured: false,
          last4: null,
          last_error: null,
          mode: "polling",
          running: false,
          secrets_enabled: true,
          updated_at: null,
          username: null,
        }),
      ),
    );
    renderAt("/admin/integrations?card=telegram&panel=open");
    const side = await panelEl();

    expect(await within(side).findByText("Состояние бота")).toBeVisible();
    expect(within(side).getByText("не работает — токен не задан")).toBeVisible();
    expect(within(side).queryByText("Работает")).toBeNull();
  });
});
