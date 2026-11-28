import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetMarks } from "../../../mocks/doNotWorkMarks";
import { resetLeads } from "../../../mocks/fixtures/leads";
import { resetNotClient } from "../../../mocks/notClient";
import { resetPictures } from "../../../mocks/pictures";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";
import { server } from "../../../test/server";

// В jsdom нет canvas: готовую картинку заменяем маленьким PNG.
vi.mock("../../../features/profile/cropExport", () => {
  const png = () =>
    Promise.resolve(
      new Blob([Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])], {
        type: "image/png",
      }),
    );
  return { renderCircle: png, renderSquare: png };
});

setupBotTests();

beforeEach(() => {
  resetLeads();
  resetMarks();
  resetNotClient();
  resetPictures();
});

async function open(email: string, path: string) {
  signIn(email);
  renderAt(path);
  expect(await screen.findByRole("heading", { level: 1, name: "Контрагенты" })).toBeVisible();
  return panelEl();
}

/** ADR-0028 (СУЩ-2.5): одна компания во всех ролях — одна карточка, роли — отметки. */
describe("Карточка контрагента", () => {
  it("клиент: шапка, роль «Клиент», вкладки; «Обзор» — люди и счета; заявки — та же карточка", async () => {
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    expect(
      await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" }),
    ).toBeVisible();
    const roles = within(panel).getByRole("list", { name: "Роли" });
    expect(within(roles).getByText("Клиент")).toBeVisible();
    // менеджер роли не отмечает: «+ Поставщик» ему не предлагается
    expect(within(roles).queryByRole("button")).toBeNull();
    expect(within(panel).getByRole("tab", { name: "Заявки и проекты" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.click(within(panel).getByRole("tab", { name: "Обзор" }));
    expect(await within(panel).findByRole("heading", { name: "Люди" })).toBeVisible();
    expect(within(panel).getByRole("heading", { name: "Банковские счета" })).toBeVisible();
    expect(within(panel).getByText("Счетов пока нет.")).toBeVisible();
  });

  it("поставщик: снабженец отмечает роль «Изготовитель» — новая карточка не нужна; занятую роль снять нельзя", async () => {
    const panel = await open("supply@demo.example", "/crm/clients?partner=1&panel=open&tab=card");
    expect(
      await within(panel).findByRole("heading", { name: "ООО «Поставщик Север»" }),
    ).toBeVisible();
    const roles = within(panel).getByRole("list", { name: "Роли" });
    const maker = within(roles).getByRole("button", { name: "+ Изготовитель" });
    expect(maker).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(maker);
    expect(await within(roles).findByRole("button", { name: "✓ Изготовитель" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(within(roles).getByRole("button", { name: "✓ Поставщик" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      "Роль занята: у компании есть предложения или бренды.",
    );

    fireEvent.click(within(panel).getByRole("tab", { name: "Обзор" }));
    expect(await within(panel).findByText("АКБ «Демо Банк»")).toBeVisible();
    // снабженцу номер счёта не показывается целиком
    expect(within(panel).getByText(/…0001/)).toBeVisible();
    expect(
      within(panel).getByText("Номера счетов видны только тем, кому открыты финансы."),
    ).toBeVisible();
  });

  it("одна компания — клиент, поставщик и изготовитель: три вкладки и бренды в «Обзоре»", async () => {
    server.use(
      http.get("*/people/clients/3/counterparty", () =>
        HttpResponse.json({
          id: "1",
          name: "ООО Рельс-Сервис Демо",
          inn: "300000003",
          registration_number: null,
          country: "Узбекистан",
          legal_address: "г. Ташкент, ул. Демо, 1",
          crm_client_id: 3,
          roles: {
            client: true,
            supplier: true,
            manufacturer: true,
            partner: true,
            organization: false,
          },
          role_states: [
            { role: "client", state: "active", kind: null },
            { role: "partner", state: "active", kind: "manufacturer" },
          ],
          cabinet: {
            opened: true,
            roles: ["client", "partner"],
            sees: "both",
            last_login_at: null,
            logged_in_contacts: 0,
          },
          people: [],
          bank_accounts: [],
          accounts_masked: false,
          brands: [{ id: "5", name: "PL-Rail" }],
        }),
      ),
    );
    const panel = await open("director@demo.example", "/crm/clients/3?panel=open&tab=card");
    const roles = await within(panel).findByRole("list", { name: "Роли" });
    expect(within(roles).getByText("Партнёр, изготовитель — действует")).toBeVisible();
    for (const name of ["Обзор", "Заявки и проекты", "Товары поставщика"]) {
      expect(within(panel).getByRole("tab", { name })).toBeVisible();
    }
    fireEvent.click(within(panel).getByRole("tab", { name: "Обзор" }));
    expect(await within(panel).findByRole("heading", { name: "Как изготовитель" })).toBeVisible();
    expect(within(panel).getByText("PL-Rail")).toBeVisible();
  });

  it("клиент ещё не передан в ERP: прежняя карточка клиента, без ролей и вкладок", async () => {
    server.use(
      http.get("*/people/clients/3/counterparty", () =>
        HttpResponse.json({ code: "NOT_FOUND", message: "x", source: "erp" }, { status: 404 }),
      ),
    );
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    expect(
      await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" }),
    ).toBeVisible();
    await waitFor(() => {
      expect(within(panel).queryByRole("tab", { name: "Обзор" })).toBeNull();
    });
  });

  it("реквизиты правятся в карточке (СУЩ-2.7): название и адрес — новые в шапке; дубль ИНН — понятный отказ", async () => {
    const panel = await open("supply@demo.example", "/crm/clients?partner=1&panel=open&tab=card");
    expect(
      await within(panel).findByRole("heading", { name: "ООО «Поставщик Север»" }),
    ).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Реквизиты" }));
    const sheet = await screen.findByRole("dialog", { name: "Реквизиты контрагента" });
    expect(within(sheet).getByRole("button", { name: "Сохранить" })).toBeDisabled();
    fireEvent.change(within(sheet).getByLabelText("Название"), {
      target: { value: "ООО «Поставщик Север-2»" },
    });
    fireEvent.change(within(sheet).getByLabelText("Юридический адрес"), {
      target: { value: "Ташкент, ул. Новая, 5" },
    });
    fireEvent.click(within(sheet).getByRole("button", { name: "Сохранить" }));
    expect(
      await within(panel).findByRole("heading", { name: "ООО «Поставщик Север-2»" }),
    ).toBeVisible();
    expect(within(panel).getByText(/Ташкент, ул\. Новая, 5/)).toBeVisible();

    server.use(
      http.patch("*/people/counterparties/:id", () =>
        HttpResponse.json(
          { code: "CONFLICT", message: "x", source: "erp", details: { reason: "company_exists" } },
          { status: 409 },
        ),
      ),
    );
    fireEvent.click(within(panel).getByRole("button", { name: "Реквизиты" }));
    const again = await screen.findByRole("dialog", { name: "Реквизиты контрагента" });
    fireEvent.change(within(again).getByLabelText("ИНН"), { target: { value: "300000999" } });
    fireEvent.click(within(again).getByRole("button", { name: "Сохранить" }));
    expect(
      await within(again).findByText("Такой ИНН или рег. номер уже у другой компании."),
    ).toBeVisible();
  });

  it("бухгалтер реквизиты не правит: кнопки нет", async () => {
    const panel = await open("accountant@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    expect(within(panel).queryByRole("button", { name: "Реквизиты" })).toBeNull();
  });
});

/** Х-8: «Не работать» — факты у компании; полоса в карточке, «Снова работать» снимает. */
describe("Карточка контрагента: «Не работать»", () => {
  it("снабженец отмечает компанию с причиной; полоса показывает причину и кто отметил; «Снова работать» снимает", async () => {
    const panel = await open("supply@demo.example", "/crm/clients?partner=1&panel=open&tab=card");
    await within(panel).findByRole("heading", { name: /Поставщик Север/ });
    expect(within(panel).queryByRole("status")).toBeNull();

    fireEvent.click(within(panel).getByRole("button", { name: "Не работать" }));
    const dialog = await screen.findByRole("dialog", { name: "С компанией не работаем" });
    const submit = within(dialog).getByRole("button", { name: "Отметить" });
    // без причины отметить нельзя
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Причина"), {
      target: { value: "Дважды не оплатил отгрузку" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    const strip = await within(panel).findByRole("status");
    expect(strip).toHaveTextContent("С компанией не работаем: Дважды не оплатил отгрузку");
    expect(strip).toHaveTextContent("Отметил:");
    expect(within(panel).queryByRole("button", { name: "Не работать" })).toBeNull();

    fireEvent.click(within(panel).getByRole("button", { name: "Снова работать" }));
    await waitFor(() => {
      expect(within(panel).queryByRole("status")).toBeNull();
    });
    expect(await within(panel).findByRole("button", { name: "Не работать" })).toBeVisible();
  });

  it("менеджер клиентов отмечает клиента — отметка видна в списке («Не работаем») и в строке клиента", async () => {
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    fireEvent.click(within(panel).getByRole("button", { name: "Не работать" }));
    const dialog = await screen.findByRole("dialog", { name: "С компанией не работаем" });
    fireEvent.change(within(dialog).getByLabelText("Причина"), {
      target: { value: "Спор по оплате" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Отметить" }));
    expect(await within(panel).findByRole("status")).toHaveTextContent("Спор по оплате");
  });

  it("бухгалтер отметку видит, но поставить её не может", async () => {
    const panel = await open("accountant@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    expect(within(panel).queryByRole("button", { name: "Не работать" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Реквизиты" })).toBeNull();
  });
});

/** ТЕСТ-1: «Тестовая» — обратимая отметка; вопрос только когда у компании есть открытые заявки. */
describe("Карточка контрагента: «Тестовая»", () => {
  it("у компании есть открытые заявки: один вопрос; потом метка «Тестовая», «Снять отметку» — без вопроса", async () => {
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    expect(within(panel).queryByText("Тестовая")).toBeNull();

    fireEvent.click(within(panel).getByRole("button", { name: "Отметить как тестовую" }));
    const ask = await screen.findByRole("dialog", { name: "Отметить как тестовую?" });
    expect(ask).toHaveTextContent("открытых заявок: 1");
    fireEvent.click(within(ask).getByRole("button", { name: "Отметить" }));

    expect(await within(panel).findByText("Тестовая")).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Отметить как тестовую" })).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "Снять отметку" }));
    await waitFor(() => {
      expect(within(panel).queryByText("Тестовая")).toBeNull();
    });
    expect(
      await within(panel).findByRole("button", { name: "Отметить как тестовую" }),
    ).toBeVisible();
  });

  it("открытых заявок нет — отмечается сразу, без вопроса", async () => {
    server.use(
      http.get("*/people/counterparties/:id/not-client", () =>
        HttpResponse.json({
          company_id: "1001",
          dry_run: true,
          is_client: true,
          requests_to_close: [],
          requests_kept: [],
          history: { quotes_sent: 0, contracts: 0, invoices: 0, projects: 0 },
          has_history: false,
          contacts: 1,
          contacts_with_cabinet: 1,
          remaining_roles: [],
          requests_closed: [],
          candidate_entry: false,
        }),
      ),
    );
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    fireEvent.click(within(panel).getByRole("button", { name: "Отметить как тестовую" }));
    expect(await within(panel).findByText("Тестовая")).toBeVisible();
    expect(screen.queryByRole("dialog", { name: "Отметить как тестовую?" })).toBeNull();
  });

  it("бухгалтер метку видит, но поставить её не может", async () => {
    const panel = await open("accountant@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    expect(within(panel).queryByRole("button", { name: "Отметить как тестовую" })).toBeNull();
  });
});

/** ЕД-5 и СУЩ-3: логотип компании и фото контакта — загрузка в карточке контрагента. */
describe("Карточка контрагента: логотип и фото контакта", () => {
  async function pick(dialogName: string, input: HTMLElement, file: File) {
    fireEvent.change(input, { target: { files: [file] } });
    const dialog = await screen.findByRole("dialog", { name: dialogName });
    // jsdom не загружает картинки: сообщаем размеры, как это сделал бы браузер.
    const img = await waitFor(() => {
      const found = dialog.querySelector("img");
      expect(found).not.toBeNull();
      return found as HTMLImageElement;
    });
    Object.defineProperty(img, "naturalWidth", { value: 400 });
    Object.defineProperty(img, "naturalHeight", { value: 300 });
    fireEvent.load(img);
    return dialog;
  }
  const PNG = () => new File([Uint8Array.from([1, 2, 3, 4])], "logo.png", { type: "image/png" });

  it("логотип: нажать на буквы → файл → квадрат → сохранить; адрес с версией; «Убрать» возвращает буквы", async () => {
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    const head = panel.querySelector(".pf-cp-head") as HTMLElement;
    expect(head.querySelector("img")).toBeNull();

    const dialog = await pick(
      "Логотип компании",
      within(head).getByLabelText("Файл логотипа", { selector: "input" }),
      PNG(),
    );
    const apply = within(dialog).getByRole("button", { name: "Сохранить логотип" });
    await waitFor(() => {
      expect(apply).toBeEnabled();
    });
    fireEvent.click(apply);

    await waitFor(() => {
      expect(head.querySelector("img")).toHaveAttribute(
        "src",
        "/api/v1/people/counterparties/1003/logo?v=v1",
      );
    });
    fireEvent.click(within(head).getByRole("button", { name: "Убрать логотип" }));
    await waitFor(() => {
      expect(head.querySelector("img")).toBeNull();
    });
    expect(within(head).getByRole("button", { name: "Загрузить логотип" })).toBeVisible();
  }, 15_000);

  it("не картинка — отказ словами, окно обрезки не открывается", async () => {
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    const head = panel.querySelector(".pf-cp-head") as HTMLElement;
    fireEvent.change(within(head).getByLabelText("Файл логотипа", { selector: "input" }), {
      target: { files: [new File(["x"], "logo.gif", { type: "image/gif" })] },
    });
    expect(await within(head).findByRole("alert")).toHaveTextContent(
      "Нужна картинка PNG, JPEG или WebP.",
    );
    expect(screen.queryByRole("dialog", { name: "Логотип компании" })).toBeNull();
  });

  it("сервер отказал по размеру — причина в окне обрезки, логотип прежний", async () => {
    server.use(
      http.put("*/people/counterparties/:id/logo", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "Проверьте заполнение полей.",
            source: "erp",
            details: { fields: ["file"], reason: "file_too_large" },
          },
          { status: 422 },
        ),
      ),
    );
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    const head = panel.querySelector(".pf-cp-head") as HTMLElement;
    const dialog = await pick(
      "Логотип компании",
      within(head).getByLabelText("Файл логотипа", { selector: "input" }),
      PNG(),
    );
    const apply = within(dialog).getByRole("button", { name: "Сохранить логотип" });
    await waitFor(() => {
      expect(apply).toBeEnabled();
    });
    fireEvent.click(apply);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Файл больше 2 МБ");
    expect(head.querySelector("img")).toBeNull();
  }, 15_000);

  it("только чтение: логотип видно, менять нельзя", async () => {
    server.use(
      http.get("*/people/clients/3/counterparty", () =>
        HttpResponse.json({
          id: "1003",
          name: "ООО Рельс-Сервис Демо",
          inn: "300000003",
          registration_number: null,
          country: null,
          legal_address: null,
          crm_client_id: 3,
          logo_url: "/api/v1/people/counterparties/1003/logo?v=abc",
          roles: {
            client: true,
            supplier: false,
            manufacturer: false,
            partner: false,
            organization: false,
          },
          role_states: [{ role: "client", state: "active", kind: null }],
          cabinet: {
            opened: true,
            roles: ["client"],
            sees: "client",
            last_login_at: null,
            logged_in_contacts: 0,
          },
          people: [],
          bank_accounts: [],
          accounts_masked: true,
          brands: [],
        }),
      ),
    );
    const panel = await open("accountant@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    const head = panel.querySelector(".pf-cp-head") as HTMLElement;
    expect(head.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/people/counterparties/1003/logo?v=abc",
    );
    expect(within(head).queryByLabelText("Файл логотипа", { selector: "input" })).toBeNull();
    expect(within(head).queryByRole("button", { name: /логотип/i })).toBeNull();
  });

  it("фото контакта: «Обзор» → файл → круг → сохранить; фото в строке человека", async () => {
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    fireEvent.click(within(panel).getByRole("tab", { name: "Обзор" }));
    const people = await within(panel).findByRole("heading", { name: "Люди" });
    const list = (people.parentElement as HTMLElement).querySelector("ul") as HTMLElement;
    const first = within(list).getAllByRole("listitem")[0] as HTMLElement;
    expect(first.querySelector("img")).toBeNull();

    const dialog = await pick(
      "Фото контакта",
      within(first).getByLabelText(/^Файл фото: /, { selector: "input" }),
      PNG(),
    );
    const apply = within(dialog).getByRole("button", { name: "Сохранить фото" });
    await waitFor(() => {
      expect(apply).toBeEnabled();
    });
    fireEvent.click(apply);
    await waitFor(() => {
      expect(first.querySelector("img")?.getAttribute("src")).toMatch(
        /^\/api\/v1\/people\/contacts\/\d+\/photo\?v=v1$/,
      );
    });
  }, 15_000);
});

/** КОНТР-1б: роли — список с состоянием каждой; «Не клиент» снимает ошибочную роль на месте. */
describe("Роли контрагента и «Не клиент»", () => {
  it("состояния ролей словами: клиент и партнёр с заявкой на подключение", async () => {
    server.use(
      http.get("*/people/clients/4/counterparty", () =>
        HttpResponse.json({
          id: "1004",
          name: "ООО Демо-Вагон",
          inn: "300000004",
          registration_number: null,
          country: "Узбекистан",
          legal_address: null,
          crm_client_id: 4,
          roles: {
            client: true,
            supplier: false,
            manufacturer: false,
            partner: true,
            organization: false,
          },
          role_states: [
            { role: "client", state: "active", kind: null },
            { role: "partner", state: "application", kind: "supplier" },
          ],
          cabinet: {
            opened: true,
            roles: ["client"],
            sees: "client",
            last_login_at: "2026-11-25T08:22:00Z",
            logged_in_contacts: 1,
          },
          people: [],
          bank_accounts: [],
          accounts_masked: false,
          brands: [],
        }),
      ),
    );
    const panel = await open("director@demo.example", "/crm/clients/4?panel=open&tab=card");
    const roles = await within(panel).findByRole("list", { name: "Роли" });
    expect(within(roles).getByText("Клиент")).toBeVisible();
    expect(
      within(roles).getByText("Партнёр, поставщик — заявка на подключение рассматривается"),
    ).toBeVisible();
  });

  it("«Не клиент» с открытой заявкой: подтверждение со списком заявок (необратимо); роль и вкладка клиента уходят, компания выходит из «Клиентов»", async () => {
    const panel = await open("director@demo.example", "/crm/clients/4?panel=open&tab=card");
    const roles = await within(panel).findByRole("list", { name: "Роли" });
    expect(within(roles).getByText("Клиент")).toBeVisible();
    expect(within(panel).getByRole("tab", { name: "Заявки и проекты" })).toBeVisible();

    fireEvent.click(within(panel).getByRole("button", { name: "Не клиент" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/Закроются как заведённые по ошибке: RQ-2026-009/),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Снять роль" }));

    await waitFor(() => {
      expect(within(panel).queryByRole("tab", { name: "Заявки и проекты" })).toBeNull();
    });
    expect(within(panel).queryByRole("button", { name: "Не клиент" })).toBeNull();
    expect(within(roles).queryByText("Клиент")).toBeNull();
  });

  it("«Не клиент» у компании с настоящей историей: предупреждение списком, решает сотрудник", async () => {
    const panel = await open("director@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("list", { name: "Роли" });
    fireEvent.click(within(panel).getByRole("button", { name: "Не клиент" }));

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/КП отправлено — 2, договоров — 1, счетов — 1/),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Останутся \(клиенту уже отправляли КП\): RQ-2026-004/),
    ).toBeInTheDocument();
    // отмена ничего не меняет
    fireEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(within(panel).getByRole("button", { name: "Не клиент" })).toBeVisible();

    fireEvent.click(within(panel).getByRole("button", { name: "Не клиент" }));
    fireEvent.click(
      await within(await screen.findByRole("dialog")).findByRole("button", {
        name: "Всё равно снять роль",
      }),
    );
    await waitFor(() => {
      expect(within(panel).queryByRole("button", { name: "Не клиент" })).toBeNull();
    });
  });

  it("без права вести клиентов и поставщиков «Не клиент» не показывается", async () => {
    const panel = await open("accountant@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("list", { name: "Роли" });
    expect(within(panel).queryByRole("button", { name: "Не клиент" })).toBeNull();
  });
});

/** КЛИЕНТ-1: «Может подтверждать» у контакта клиента — тот же переключатель, что у партнёра; без права в Кабинете просмотр. */
describe("Карточка контрагента: «Может подтверждать» клиентского контакта", () => {
  it("менеджер клиентов включает и снимает право у каждого контакта", async () => {
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    fireEvent.click(await within(panel).findByRole("tab", { name: "Обзор" }));
    const switches = await within(panel).findAllByRole("switch");
    expect(switches.length).toBeGreaterThanOrEqual(2);
    const [first, second] = switches as [HTMLElement, HTMLElement];
    expect(first).toBeChecked();
    expect(second).not.toBeChecked();

    fireEvent.click(second);
    await waitFor(() => {
      expect(second).toBeChecked();
    });
    fireEvent.click(first);
    await waitFor(() => {
      expect(first).not.toBeChecked();
    });
  });

  it("сотрудник без права на реквизиты видит право, но не меняет", async () => {
    const panel = await open("accountant@demo.example", "/crm/clients/3?panel=open&tab=card");
    fireEvent.click(await within(panel).findByRole("tab", { name: "Обзор" }));
    const [first] = await within(panel).findAllByRole("switch");
    expect(first).toBeDisabled();
  });
});
