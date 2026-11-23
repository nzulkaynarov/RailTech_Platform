import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pickRowAction, rowActionItems } from "../../../test/rowActions";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import {
  MOCK_LOGO,
  readCompanyMock,
  resetCompanyMock,
  updateCompanyMock,
} from "../../../mocks/fixtures/company";
import { readEmployees, writeEmployees } from "../../../mocks/fixtures/employees";
import { readRoles, writeRoles } from "../../../mocks/fixtures/roles";
import { endSession } from "../../../mocks/mockSession";
import { companyDayKey } from "../../../shared/lib/dates";
import i18n from "../../../shared/i18n";
import { fillDate } from "../../../test/fields";
import { renderApp, signInAs } from "../../../test/renderApp";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  resetCompanyMock();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  vi.restoreAllMocks();
  endSession();
});

/**
 * Загрузка логотипа: jsdom-овый `FormData` не понимает встроенный в Node `fetch`, поэтому в vitest запрос перехватывается на
 * уровне `fetch` (проверяется, что ушёл файл в поле `logo`); настоящую `multipart`-загрузку через MSW проверяет e2e.
 */
function stubLogoUpload(path: "/admin/company/logo" | "/admin/company/brand/logo") {
  const original = globalThis.fetch;
  const seen: { name: string; type: string }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    if (typeof input === "string" && input.endsWith(path) && init?.method === "POST") {
      const file = (init.body as FormData).get("logo") as File;
      seen.push({ name: file.name, type: file.type });
      const body = updateCompanyMock((state) => {
        if (path === "/admin/company/logo") {
          state.company = { ...state.company, logo_url: MOCK_LOGO };
          return state.company;
        }
        state.brand = { ...state.brand, logo_url: MOCK_LOGO };
        return state.brand;
      });
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }
    return original(input, init);
  });
  return seen;
}

/** Бывшие вкладки «Компании и бланков» после SET-IA — страницы своих групп; старый адрес уводит на новую. */
const PAGE_OF: Record<string, string> = {
  details: "Реквизиты и бланк",
  brand: "Реквизиты и бланк",
  numbering: "Нумерация",
  quote: "Продажи",
  templates: "Шаблоны",
  charges: "Справочники",
  reference: "Справочники",
  categories: "Справочники",
  platform: "Налоги и валюты",
};

async function openTab(tab: string, email = "director@demo.example") {
  signInAs(email);
  renderApp(`/admin/company?tab=${tab}`);
  await screen.findByRole("heading", { level: 1, name: PAGE_OF[tab] ?? "Реквизиты и бланк" });
}

const button = (name: string | RegExp) => screen.findByRole("button", { name });

function type(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("Admin · Компания: реквизиты для счетов (D26G-6)", () => {
  it("нет счёта в сумах — предупреждение; добавили счёт — «Основной счёт в сумах задан» (счета — список, 2026-11-11)", async () => {
    updateCompanyMock((state) => {
      state.bankAccounts = [];
    });
    await openTab("details", "admin@demo.example");
    // реквизиты — секциями (§4.1a): счета — третья секция
    fireEvent.click(
      await screen.findByRole("button", { name: /Банковские счета/, expanded: false }),
    );

    expect(await screen.findByText(/Нет основного счёта в сумах/)).toBeVisible();
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Добавить счёт" }))[0] as HTMLElement,
    );
    const dialog = await screen.findByRole("region", { name: "Новый банковский счёт" });
    fireEvent.change(within(dialog).getByLabelText("Расчётный счёт"), {
      target: { value: "20208000900000000001" },
    });
    fireEvent.change(within(dialog).getByLabelText("МФО"), { target: { value: "00014" } });
    await waitFor(() => {
      expect(within(dialog).getByLabelText("Банк")).toHaveValue("АКБ «Демо Банк»");
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Основной счёт в сумах задан.")).toBeVisible();
    const [account] = readCompanyMock().bankAccounts;
    expect([account?.account, account?.currency, account?.is_default]).toEqual([
      "20208000900000000001",
      "UZS",
      true,
    ]);
  });
});

describe("Admin · Компания: «нет реквизитов для счетов» ведёт туда, где пусто (СЦ-3)", () => {
  it.each([
    ["ИНН", { inn: "" }, /Компания/],
    ["юридического адреса", { legal_address: "" }, /Контакты/],
    ["расчётного счёта", {}, /Банковские счета/],
  ])("нет %s — открыта эта секция", async (_what, patch, section) => {
    updateCompanyMock((state) => {
      state.company = { ...state.company, ...patch };
    });
    signInAs("admin@demo.example");
    renderApp("/admin/company?section=bank");
    expect(await screen.findByRole("button", { name: section, expanded: true })).toBeVisible();
  });
});

describe("Admin · Компания: банк по МФО из справочника (план 2.9, ADR-0029)", () => {
  it("МФО ищется по названию; банк из справочника не правится; МФО не из справочника — предупреждение и банк вручную", async () => {
    updateCompanyMock((state) => {
      state.bankAccounts = [];
    });
    await openTab("details", "admin@demo.example");
    fireEvent.click(
      await screen.findByRole("button", { name: /Банковские счета/, expanded: false }),
    );
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Добавить счёт" }))[0] as HTMLElement,
    );
    const dialog = await screen.findByRole("region", { name: "Новый банковский счёт" });
    const mfo = within(dialog).getByLabelText("МФО");
    const bank = within(dialog).getByLabelText("Банк");
    fireEvent.focus(mfo);
    fireEvent.change(mfo, { target: { value: "демо" } });
    fireEvent.click(await screen.findByText("00014 · АКБ «Демо Банк»"));
    await waitFor(() => {
      expect(mfo).toHaveValue("00014");
    });
    expect(bank).toHaveValue("АКБ «Демо Банк»");
    expect(bank).toHaveAttribute("readonly");

    fireEvent.change(mfo, { target: { value: "01999" } });
    expect(
      await within(dialog).findByText("Нет в справочнике ЦБ — проверьте МФО и впишите банк"),
    ).toBeInTheDocument();
    expect(bank).toHaveValue("");
    expect(bank).not.toHaveAttribute("readonly");
  });
});

describe("Admin · Компания: справочник банков ещё пуст (СЦ-3)", () => {
  it("свежая установка без справочника ЦБ: МФО не найден — предупреждение и банк вписывается вручную", async () => {
    server.use(http.get("*/dictionaries/banks", () => HttpResponse.json({ items: [] })));
    updateCompanyMock((state) => {
      state.bankAccounts = [];
    });
    await openTab("details", "admin@demo.example");
    fireEvent.click(
      await screen.findByRole("button", { name: /Банковские счета/, expanded: false }),
    );
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Добавить счёт" }))[0] as HTMLElement,
    );
    const dialog = await screen.findByRole("region", { name: "Новый банковский счёт" });
    const bank = within(dialog).getByLabelText("Банк");
    fireEvent.change(within(dialog).getByLabelText("МФО"), { target: { value: "00999" } });
    expect(
      await within(dialog).findByText("Нет в справочнике ЦБ — проверьте МФО и впишите банк"),
    ).toBeInTheDocument();
    expect(bank).not.toHaveAttribute("readonly");
  });
});

describe("Admin · Компания: доступ и каркас", () => {
  it("директор и администратор открывают раздел; заголовок «Реквизиты и бланк», подзаголовок — название компании (SET-IA)", async () => {
    await openTab("details", "admin@demo.example");
    expect(await screen.findByText("ООО «Демо Рейл»", { selector: "div" })).toBeInTheDocument();
    // Одна страница с частями вместо девяти вкладок: вкладок нет
    expect(screen.queryByRole("tab")).toBeNull();
    expect(
      screen.getByRole("heading", { level: 2, name: "Реквизиты компании" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { level: 2, name: "Бланк и бренд документов" }),
    ).toBeInTheDocument();
    // Контакты, которые бот называет клиентам (раздел `company` настроек бота) — на этой же странице
    expect(
      await screen.findByRole("heading", { level: 2, name: "Контакты для клиентов" }),
    ).toBeInTheDocument();
  });

  it("без раздела `company.settings` пункт «Компания» скрыт в меню, а прямой адрес даёт «Нет доступа»", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/company");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Нет доступа" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Реквизиты и бланк" })).toBeNull();
  });

  it("администратор видит «Реквизиты и бланк» в меню слева страниц группы «Компания»; ⚙ с `?group=` ведёт на первую страницу группы (ЕВ-2а)", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin?group=company");
    const nav = await screen.findByRole("navigation", { name: "Страницы группы «Компания»" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Реквизиты и бланк", "Нумерация", "Налоги и валюты", "Статьи компании"]);
    expect(within(nav).getByRole("link", { name: "Реквизиты и бланк" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("своей компании в ERP нет — слово и действие «Проверить снова», а не пустая страница", async () => {
    server.use(
      http.get("*/admin/company", () =>
        HttpResponse.json(
          { code: "COMPANY_NOT_SET", message: "нет", source: "erp" },
          { status: 409 },
        ),
      ),
    );
    await openTab("details");
    expect(
      await screen.findByRole("heading", { name: "Ваша компания ещё не создана" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить снова" })).toBeInTheDocument();
  });

  it("доступ «чтение»: поля заблокированы и сказано почему", async () => {
    const roles = readRoles();
    writeRoles([
      ...roles,
      {
        id: "50",
        name: "Читатель настроек",
        description: "",
        system: false,
        version: 1,
        access: { "dashboard.queue": "full", "company.settings": "read" },
        restricted_fields: [],
        updated_at: "2026-10-26T00:00:00.000Z",
      },
    ]);
    writeEmployees(
      readEmployees().map((e) => (e.id === "u-demo-manager" ? { ...e, role_ids: ["50"] } : e)),
    );
    await openTab("details", "manager@demo.example");
    expect(
      await screen.findByText(/доступ к настройкам компании только для чтения/),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Телефон")).toBeDisabled();
    // Без правок бар сохранения скрыт: кнопки сохранения нет (UX-1b, S6)
    expect(screen.queryByRole("button", { name: "Сохранить реквизиты" })).toBeNull();
  });

  it("доступ «чтение»: вкладки и вид образца переключаются, а поля и кнопки изменения остаются заблокированными", async () => {
    writeRoles([
      ...readRoles(),
      {
        id: "50",
        name: "Читатель настроек",
        description: "",
        system: false,
        version: 1,
        access: { "dashboard.queue": "full", "company.settings": "read" },
        restricted_fields: [],
        updated_at: "2026-10-26T00:00:00.000Z",
      },
    ]);
    writeEmployees(
      readEmployees().map((e) => (e.id === "u-demo-manager" ? { ...e, role_ids: ["50"] } : e)),
    );
    await openTab("details", "manager@demo.example");
    await screen.findByLabelText("Телефон");

    // Бланк — на той же странице; поля заблокированы, вид образца переключается
    expect(await screen.findByLabelText("Подписант")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Сохранить бланк" })).toBeNull();
    await screen.findByTitle("Образец: КП");
    fireEvent.click(screen.getByText("Договор", { selector: ".ant-segmented-item-label" }));
    await waitFor(() => {
      expect(screen.getByTitle("Образец: Договор").getAttribute("srcdoc")).toContain(
        "Договор поставки",
      );
    });

    // «Шаблоны» — пункт «Документов»
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Модули" })).getByRole("link", {
        name: "Документы",
      }),
    );
    fireEvent.click(
      within(await screen.findByRole("navigation", { name: "Разделы модуля" })).getByRole("link", {
        name: "Шаблоны",
      }),
    );
    // Раздел открывается на «Все шаблоны» (план 2.7): шаблоны документов — своя вкладка
    fireEvent.click(await screen.findByRole("tab", { name: "Документы" }));
    fireEvent.click(await screen.findByRole("button", { name: "Открыть: Договор поставки (наш)" }));
    const viewer = await screen.findByRole("region", { name: "Шаблон документа" });
    expect(within(viewer).getByLabelText(/^Текст шаблона/)).toBeDisabled();
    expect(within(viewer).queryByRole("button", { name: "Сохранить" })).toBeNull();
    expect(await within(viewer).findByTitle("Образец документа по шаблону")).toBeInTheDocument();
    fireEvent.click(within(viewer).getByRole("button", { name: "К списку" }));
    expect(screen.getByRole("button", { name: "Создать шаблон" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /^Изменить:/ })).toBeNull();

    // Справочники расчёта — страница «Правила работы · Справочники»: открыта и с одним `company.settings`
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Модули" })).getByRole("link", {
        name: "Настройки",
      }),
    );
    fireEvent.click(
      await within(await screen.findByRole("navigation", { name: "Разделы модуля" })).findByRole(
        "link",
        { name: "Правила работы" },
      ),
    );
    fireEvent.click(await screen.findByRole("link", { name: "Справочники" }));
    expect(await screen.findByText("Казахстан")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить значение" })).toBeDisabled();
    fireEvent.click(screen.getByRole("link", { name: "Валюты" }));
    expect(await screen.findByText("Евро")).toBeInTheDocument();
  });
});

describe("Реквизиты и логотип", () => {
  it("правка телефона: бар «Сохранить реквизиты» появляется только при изменении, в ERP уходит одно поле", async () => {
    await openTab("details");
    await screen.findByLabelText("Телефон");
    expect(screen.queryByRole("button", { name: "Сохранить реквизиты" })).toBeNull();

    type("Телефон", "+998 11 111 11 11");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Сохранить реквизиты" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить реквизиты" }));

    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().company.phone).toBe("+998 11 111 11 11");
    expect(readCompanyMock().company.name).toBe("ООО «Демо Рейл»");
    // Сохранение настройки — без блока «Что произойдёт» (CONVENTIONS §2 п. 8, S1)
    expect(screen.queryByRole("group", { name: "Что произойдёт" })).toBeNull();
  });

  it("неверный ИНН: сообщение у поля, запрос не уходит", async () => {
    await openTab("details");
    await screen.findByLabelText(/^ИНН/);
    type(/^ИНН/, "12");
    fireEvent.click(await button("Сохранить реквизиты"));

    expect(await screen.findByText("ИНН — 9 цифр")).toBeInTheDocument();
    expect(readCompanyMock().company.inn).toBe("123456789");
  });

  it("Х-18: галочка шага «Компания» — только при ИНН из 9 цифр; «Контакты» — только при верной почте", async () => {
    await openTab("details");
    await screen.findByLabelText(/^ИНН/);
    const head = (name: RegExp) => screen.getByRole("button", { name });
    const ticked = (el: HTMLElement) =>
      el.querySelector(".pf-fstep-badge svg") !== null &&
      el.closest("li")?.getAttribute("data-invalid") === null;

    type(/^ИНН/, "12");
    fireEvent.click(head(/^Контакты/));
    expect(ticked(head(/^Компания/))).toBe(false);

    fireEvent.click(head(/^Компания/));
    type(/^ИНН/, "123456789");
    fireEvent.click(head(/^Контакты/));
    expect(ticked(head(/^Компания/))).toBe(true);

    for (const bad of ["not-an-email", "info@railtech.u", "a..b@x.uz", "a@x_y.uz"]) {
      type("Почта компании", bad);
      fireEvent.click(head(/^Компания/));
      expect(ticked(head(/^Контакты/)), bad).toBe(false);
      fireEvent.click(head(/^Контакты/));
    }
    type("Почта компании", "info@railtech.uz");
    fireEvent.click(head(/^Компания/));
    expect(ticked(head(/^Контакты/))).toBe(true);
  });

  it("логотип: загрузка файла и удаление", async () => {
    await openTab("details");
    const input = await screen.findByLabelText("Выбрать файл: Логотип компании");
    expect(screen.getAllByText("Нет логотипа").length).toBeGreaterThan(0);
    const seen = stubLogoUpload("/admin/company/logo");

    const file = new File(["png"], "logo.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText("Логотип загружен")).toBeInTheDocument();
    expect(seen).toEqual([{ name: "logo.png", type: "image/png" }]);
    expect(readCompanyMock().company.logo_url).toMatch(/^data:image/);
    fireEvent.click(await button("Удалить логотип"));
    const confirm = await screen.findByRole("dialog", { name: "Удалить логотип компании?" });
    expect(readCompanyMock().company.logo_url).toMatch(/^data:image/);
    fireEvent.click(within(confirm).getByRole("button", { name: "Удалить логотип" }));
    expect(await screen.findByText("Логотип удалён")).toBeInTheDocument();
    expect(readCompanyMock().company.logo_url).toBeNull();
  });

  it("файл больше 2 МБ не уходит в BFF", async () => {
    await openTab("details");
    const input = await screen.findByLabelText("Выбрать файл: Логотип компании");
    const big = new File([new Uint8Array(2 * 1024 * 1024 + 1)], "big.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [big] } });
    expect(await screen.findByText("Файл больше 2 МБ.")).toBeInTheDocument();
    expect(readCompanyMock().company.logo_url).toBeNull();
  });
});

describe("Бланк и бренд", () => {
  it("«Оформление», «Шрифт» и «Второй цвет» не показаны и при сохранении не уходят (ДОК-13)", async () => {
    await openTab("brand");
    await screen.findByLabelText("Основной цвет");
    for (const label of ["Оформление", "Шрифт", "Второй цвет"]) {
      expect(screen.queryByLabelText(label)).toBeNull();
    }
    type("Основной цвет", "#047857");
    fireEvent.click(await button("Сохранить бланк"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    const { brand } = readCompanyMock();
    expect(brand.accent_color).toBe("#047857");
    // в моке остались прежние значения: поля не отправлялись
    expect([brand.layout_preset, brand.font_family, brand.secondary_color]).toEqual([
      "boxed",
      "sans",
      "#595959",
    ]);
  });

  it("образец документа в изолированной рамке меняется вместе с несохранённой правкой цвета", async () => {
    await openTab("brand");
    const frame = await screen.findByTitle("Образец: КП");
    expect(frame).toHaveAttribute("sandbox", "");
    await waitFor(() => {
      expect(frame.getAttribute("srcdoc")).toContain("#1668dc");
    });

    type("Основной цвет", "#047857");
    await waitFor(() => {
      expect(screen.getByTitle("Образец: КП").getAttribute("srcdoc")).toContain("#047857");
    });
    // ничего не сохранено
    expect(readCompanyMock().brand.accent_color).toBe("#1668dc");
  });

  it("бланк на узбекском и английском (TPL-3): варианты полей сохраняются, пустое печатается по-русски", async () => {
    await openTab("brand");
    await screen.findByTitle("Образец: КП");
    fireEvent.click(screen.getByRole("button", { name: /Бланк на узбекском и английском/ }));
    const uz = screen.getByRole("group", { name: "O‘zbekcha (UZ)" });
    expect(within(uz).getByLabelText("Должность подписанта")).toHaveValue("Direktor");
    fireEvent.change(within(uz).getByLabelText("Название компании"), {
      target: { value: "«Demo Temir Yo‘l» MChJ" },
    });
    const en = screen.getByRole("group", { name: "English (EN)" });
    fireEvent.change(within(en).getByLabelText("Подвал"), {
      target: { value: "Tashkent, Uzbekistan" },
    });
    fireEvent.click(await button("Сохранить бланк"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    const saved = readCompanyMock().brand.translations;
    expect(saved.uz?.legal_name).toBe("«Demo Temir Yo‘l» MChJ");
    expect(saved.uz?.signatory_position).toBe("Direktor");
    expect(saved.en?.footer_text).toBe("Tashkent, Uzbekistan");
  });

  it("вид документа переключает образец; сохранение уходит с изменённым полем", async () => {
    await openTab("brand");
    await screen.findByTitle("Образец: КП");
    fireEvent.click(screen.getByText("Договор", { selector: ".ant-segmented-item-label" }));
    await waitFor(() => {
      expect(screen.getByTitle("Образец: Договор").getAttribute("srcdoc")).toContain(
        "Договор поставки",
      );
    });

    type("Подписант", "Демо Подписантов");
    fireEvent.click(await button("Сохранить бланк"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().brand.signatory_name).toBe("Демо Подписантов");
  });

  it("неверный цвет: сообщение, ничего не сохранено", async () => {
    await openTab("brand");
    await screen.findByLabelText("Основной цвет");
    type("Основной цвет", "red");
    fireEvent.click(await button("Сохранить бланк"));
    expect(await screen.findByText("Цвет в формате #RRGGBB")).toBeInTheDocument();
    expect(readCompanyMock().brand.accent_color).toBe("#1668dc");
  });

  it("логотип бланка загружается отдельно от логотипа компании", async () => {
    await openTab("brand");
    const input = await screen.findByLabelText("Выбрать файл: Логотип бланка");
    stubLogoUpload("/admin/company/brand/logo");
    fireEvent.change(input, {
      target: { files: [new File(["x"], "b.png", { type: "image/png" })] },
    });
    expect(await screen.findByText("Логотип загружен")).toBeInTheDocument();
    expect(readCompanyMock().brand.logo_url).toMatch(/^data:image/);
    expect(readCompanyMock().company.logo_url).toBeNull();
  });
});

describe("Нумерация", () => {
  it("образец номеров по схеме; смена префикса пересчитывает образец", async () => {
    await openTab("numbering");
    const list = await screen.findByRole("list", { name: "Образец номеров" });
    await waitFor(() => {
      expect(within(list).getByText(/DEMO-QT-\d{4}\/001/)).toBeInTheDocument();
    });

    type("Префикс нумерации", "ACME");
    await waitFor(() => {
      expect(screen.getByText(/ACME-QT-\d{4}\/001/)).toBeInTheDocument();
    });
    expect(readCompanyMock().numbering.prefix).toBe("DEMO");
    // все виды номеров в образце; у заявки — свой формат с тем же обозначением из схемы
    expect(within(list).getByText(/^RQ-\d{4}-001$/)).toBeInTheDocument();
  });

  it("умолчание SPEC-v3 §2.2 — формат «Стандартный», прежняя маска узнаётся как «Через дефис»", async () => {
    await openTab("numbering");
    expect(await screen.findByRole("radio", { name: /Стандартный/ })).toBeChecked();
    type("Маска номера", "{prefix}{type}-{YYYY}-{seq}");
    await waitFor(() => {
      expect(screen.getByRole("radio", { name: /Через дефис/ })).toBeChecked();
    });
  });

  it("маска без {seq}: сохранить нельзя, образца нет", async () => {
    await openTab("numbering");
    await screen.findByLabelText("Маска номера");
    type("Маска номера", "{type}-");
    expect(await screen.findByText("В маске обязателен токен {seq}")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить нумерацию" })).toBeDisabled();
    expect(screen.getByText(/Укажите корректную маску/)).toBeInTheDocument();
  });

  it("сохранение: схема в ERP, строка-пояснение про будущие номера вместо «Что произойдёт»", async () => {
    await openTab("numbering");
    await screen.findByLabelText("Ширина счётчика");
    fireEvent.change(screen.getByLabelText("Ширина счётчика"), { target: { value: "6" } });
    expect(
      screen.getByText("Новые номера пойдут по этой схеме; выданные не меняются."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Что произойдёт" })).toBeNull();
    fireEvent.click(await button("Сохранить нумерацию"));

    expect(await screen.findByText("Нумерация сохранена")).toBeInTheDocument();
    expect(readCompanyMock().numbering.padding).toBe(6);
  });

  it("префикс занят другой компанией — понятная ошибка у поля", async () => {
    await openTab("numbering");
    await screen.findByLabelText("Префикс нумерации");
    type("Префикс нумерации", "TAKEN");
    fireEvent.click(await button("Сохранить нумерацию"));
    expect(await screen.findByText("Префикс занят другой компанией")).toBeInTheDocument();
    expect(readCompanyMock().numbering.prefix).toBe("DEMO");
  });

  it("обозначение вида — только латиница и цифры: кириллица не сохраняется (СЦ-5)", async () => {
    await openTab("numbering");
    await screen.findByLabelText("Заявка");
    const before = JSON.stringify(readCompanyMock().numbering.type_labels);
    type("Заявка", "ЗВ");
    expect(await screen.findByText("Только латинские буквы A-Z и цифры")).toBeInTheDocument();
    fireEvent.click(await button("Сохранить нумерацию"));
    await waitFor(() => {
      expect(screen.getByText("Только латинские буквы A-Z и цифры")).toBeInTheDocument();
    });
    expect(JSON.stringify(readCompanyMock().numbering.type_labels)).toBe(before);

    type("Заявка", "RQ1");
    await waitFor(() => {
      expect(screen.queryByText("Только латинские буквы A-Z и цифры")).toBeNull();
    });
  });

  it("пустой префикс: схема всё равно действует, обозначения всех видов номеров правятся", async () => {
    await openTab("numbering");
    await screen.findByLabelText("Префикс нумерации");
    type("Префикс нумерации", "");
    expect(screen.queryByText(/действует только с префиксом/)).toBeNull();
    for (const kind of ["Заявка", "Проект", "Заказ поставщику", "Отгрузка", "Договор партнёра"]) {
      expect(screen.getByLabelText(kind)).toBeInTheDocument();
    }
  });
});

describe("Условия КП: маржа — группа cost_margin", () => {
  it("директор видит и меняет маржу", async () => {
    await openTab("quote");
    expect(await screen.findByLabelText("Минимальная маржа, %")).toHaveDisplayValue(/^5/);
    fireEvent.change(screen.getByLabelText("Минимальная маржа, %"), { target: { value: "6" } });
    fireEvent.click(await button("Сохранить условия"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().quote.min_margin_percent).toBe("6");
  });

  it("сроки цен партнёров и напоминаний об акте — настройки, а не константы (задача «Н3c»)", async () => {
    await openTab("quote");
    const expiring = await screen.findByLabelText(
      "Предупреждать об окончании цены партнёра, за дней",
    );
    expect(expiring).toHaveDisplayValue("14");
    // свежесть цен поставщиков — своя карточка рядом с каталогом, не «Условия нового КП» (ЕВ-2а, стр. 13)
    expect(expiring.closest("form")).not.toContainElement(
      screen.getByLabelText("Срок действия КП, дней"),
    );
    fireEvent.change(expiring, { target: { value: "7" } });
    fireEvent.click(await button("Сохранить сроки"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().quote.offer_expiring_days).toBe(7);
  });

  it("администратор не видит маржу: полей нет, сказано почему, остальное правится", async () => {
    await openTab("quote", "admin@demo.example");
    await screen.findByLabelText("Срок действия КП, дней");
    expect(screen.queryByLabelText("Минимальная маржа, %")).toBeNull();
    expect(screen.getByText(/Поля маржи скрыты/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Срок действия КП, дней"), { target: { value: "21" } });
    fireEvent.click(await button("Сохранить условия"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().quote.default_offer_validity_days).toBe(21);
    expect(readCompanyMock().quote.min_margin_percent).toBe("5.00");
  });
});

describe("Условия КП разошлись по страницам своих дел (ДОК-13)", () => {
  it("в «Шаблонах документов» вкладки «Условия КП» нет; старый адрес ведёт в «Продажи»", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/templates");
    await screen.findByRole("heading", { level: 1, name: "Шаблоны" });
    expect(screen.queryByRole("tab", { name: "Условия КП" })).toBeNull();
  });

  it("«Продажи»: срок, каталог и свежесть цен поставщиков — три части, валюты и напоминаний здесь нет", async () => {
    await openTab("quote");
    expect(await screen.findByLabelText("Срок действия КП, дней")).toBeInTheDocument();
    expect(screen.getByLabelText("Цена в каталоге")).toBeInTheDocument();
    expect(screen.queryByLabelText("Валюта себестоимости")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("«Налоги и валюты»: валюта и возраст курса сохраняются, поля «Продаж» не уходят", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/taxes");
    await screen.findByRole("heading", { level: 1, name: "Налоги и валюты" });
    fireEvent.change(await screen.findByLabelText("Предельный возраст курса, дней"), {
      target: { value: "5" },
    });
    expect(screen.queryByLabelText("Срок действия КП, дней")).toBeNull();
    fireEvent.click(await button("Сохранить условия"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().quote.fx_rate_max_age_days).toBe(5);
  });
});

describe("Условия КП: напоминания о просрочке (NOTIFY-2)", () => {
  it("по умолчанию выключено; включение сохраняется на странице «Уведомления»", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/notifications");
    await screen.findByRole("heading", { level: 1, name: "Уведомления" });
    const toggle = await screen.findByRole("switch", {
      name: "Напоминать клиентам о просроченных счетах",
    });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    fireEvent.click(await button("Сохранить напоминания"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().quote.remind_overdue_invoices).toBe(true);
  });
});

describe("Статьи расхода", () => {
  it("список по базисам, изменение суммы и удаление с блоком «Что произойдёт»", async () => {
    await openTab("charges");
    expect(await screen.findByText("Страхование груза")).toBeInTheDocument();

    await pickRowAction("Фрахт · FCA", "Изменить");
    const dialog = await screen.findByRole("region", { name: "Изменить статью расхода" });
    fireEvent.change(within(dialog).getByLabelText("Сумма"), { target: { value: "1800" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().charges[0]?.default_amount).toBe("1800");

    await pickRowAction("Таможенное оформление · DAP", "Удалить");
    const confirm = await screen.findByRole("dialog", { name: /Удалить статью/ });
    fireEvent.click(within(confirm).getByRole("button", { name: "Удалить" }));
    await waitFor(() => {
      expect(readCompanyMock().charges.map((c) => c.id)).toEqual(["1", "2"]);
    });
  });

  it("пустой список — слова и действие «Добавить статью»", async () => {
    server.use(
      http.get("*/admin/company/charge-templates", () => HttpResponse.json({ items: [] })),
    );
    await openTab("charges");
    expect(await screen.findByText("Статей расхода пока нет")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Добавить статью" })).toHaveLength(1);
  });
});

describe("Шаблоны документов и писем", () => {
  it("образец платформы нельзя править — его копируют к себе", async () => {
    await openTab("templates");
    expect(await screen.findByText("Образец: договор поставки")).toBeInTheDocument();
    await pickRowAction("Образец: договор поставки", "Скопировать к себе");
    const dialog = await screen.findByRole("dialog", { name: /Скопировать/ });
    expect(within(dialog).getByLabelText("Название")).toHaveValue(
      "Образец: договор поставки (копия)",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Скопировать к себе" }));
    expect(await screen.findByText("Копия создана")).toBeInTheDocument();
    expect(readCompanyMock().docTemplates.filter((t) => t.is_owned)).toHaveLength(3);
  });

  it("образец открывается по названию (только чтение, предпросмотр на каркасе вида), «Скопировать к себе» — в меню строки", async () => {
    const previews: { kind?: string }[] = [];
    server.use(
      http.post("*/admin/company/document-templates/preview", async ({ request }) => {
        previews.push((await request.json()) as { kind?: string });
        return HttpResponse.json({ html: "<p>образец</p>" });
      }),
    );
    await openTab("templates");
    const view = await screen.findByRole("button", {
      name: "Просмотр: Образец: договор поставки",
    });
    expect(view).not.toHaveClass("ant-btn-primary");
    expect(await rowActionItems("Образец: договор поставки")).toEqual(["Скопировать к себе"]);

    fireEvent.click(view);
    const dialog = await screen.findByRole("region", { name: "Образец платформы" });
    expect(within(dialog).getByText(/Образец только для просмотра/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/^Текст шаблона/)).toBeDisabled();
    expect(within(dialog).queryByRole("button", { name: "Сохранить" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "К списку" })).toBeInTheDocument();
    await waitFor(() => {
      expect(previews.at(-1)?.kind).toBe("contract"); // каркас своего вида
    });
  });

  it("новый шаблон: вид выбирается, текст подсказки — {{counterparty.name}}, образец вида подставляется", async () => {
    updateCompanyMock((state) => {
      state.docTemplates.push({
        id: "4",
        name: "Образец: акт",
        kind: "act",
        kind_name: "Акт",
        body_html: "<p>Акт</p>{{doc.items_table}}{{doc.totals}}{{doc.signatures}}",
        is_sample: true,
        is_owned: false,
        is_active: true,
        placeholders_used: [],
        updated_at: "2026-10-27T10:00:00Z",
      });
    });
    await openTab("templates");
    fireEvent.click(await screen.findByRole("button", { name: "Создать шаблон" }));
    const dialog = await screen.findByRole("region", { name: "Новый шаблон документа" });
    // ДОК-13: «Произвольного» вида нет — новый шаблон начинается с образца договора и не пуст
    expect(within(dialog).getByLabelText(/^Текст шаблона/)).not.toHaveValue("");
    expect(within(dialog).getByText(/Подставлен образец платформы/)).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Название"), { target: { value: "Мой акт" } });
    fireEvent.mouseDown(within(dialog).getByRole("combobox", { name: "Вид документа" }));
    fireEvent.click(
      await screen.findByText("Акт", { selector: ".ant-select-item-option-content" }),
    );
    expect(within(dialog).getByLabelText(/^Текст шаблона/)).toHaveValue(
      "<p>Акт</p>{{doc.items_table}}{{doc.totals}}{{doc.signatures}}",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    const created = readCompanyMock().docTemplates.find((t) => t.name === "Мой акт");
    expect(created?.kind).toBe("act");
  });

  it("редактор документа: подстановки, образец в рамке и предупреждение об неизвестной подстановке", async () => {
    await openTab("templates");
    await pickRowAction("Акт приёмки", "Изменить");
    const dialog = await screen.findByRole("region", { name: "Изменить шаблон документа" });
    const frame = await within(dialog).findByTitle("Образец документа по шаблону");
    await waitFor(() => {
      expect(frame.getAttribute("srcdoc")).toContain("[seller_name]");
    });

    fireEvent.change(within(dialog).getByLabelText(/^Текст шаблона/), {
      target: { value: "<p>{{buyer_name}} {{mystery}}</p>" },
    });
    expect(
      await within(dialog).findByText("Неизвестная подстановка {{mystery}}"),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().docTemplates.find((t) => t.id === "3")?.body_html).toContain(
      "mystery",
    );
  });

  it("неизвестная подстановка отмечена в списке «Подстановки» (C2A-G-5)", async () => {
    await openTab("templates");
    await pickRowAction("Акт приёмки", "Изменить");
    const dialog = await screen.findByRole("region", { name: "Изменить шаблон документа" });

    fireEvent.change(within(dialog).getByLabelText(/^Текст шаблона/), {
      target: { value: "<p>{{buyer_name}} {{mystery}}</p>" },
    });

    // jsdom не раскрывает <details> сам: видимость списка проверяет e2e
    expect(
      await within(dialog).findByText("Нет в списке — в документ попадут как есть"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Доступные подстановки · Неизвестные подстановки: 1/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("{{mystery}}", { selector: "code" })).toBeInTheDocument();
  });

  it("договор без обязательных блоков: окно называет недостающие, а не «проверьте поля» (C2A-G-5)", async () => {
    await openTab("templates");
    await pickRowAction("Договор поставки (наш)", "Изменить");
    const dialog = await screen.findByRole("region", { name: "Изменить шаблон документа" });

    fireEvent.change(within(dialog).getByLabelText(/^Текст шаблона/), {
      target: { value: "<p>{{buyer_name}}</p>" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("В тексте не хватает обязательных блоков документа.");
    expect(alert).toHaveTextContent("Блок: спецификация (Приложение № 1) — {{doc.spec_table}}");
    expect(alert).toHaveTextContent("Блок: итоги и НДС — {{doc.totals}}");
    expect(alert).toHaveTextContent(
      "Блок: реквизиты и подписи Сторон — {{doc.requisites_and_signatures}}",
    );
    expect(alert).toHaveTextContent("снимите «Шаблон действует»");
    // черновик (шаблон выключен) сохраняется без блоков
    fireEvent.click(within(dialog).getByLabelText("Шаблон действует"));
    fireEvent.click(await within(dialog).findByRole("button", { name: /Сохранить/ }));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
  });

  it("шаблон, по которому уже оформлены документы, удалить нельзя — слова, а не код", async () => {
    await openTab("templates");
    await pickRowAction("Договор поставки (наш)", "Удалить");
    const dialog = await screen.findByRole("dialog", { name: /Удалить шаблон/ });
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));
    expect(
      await within(dialog).findByText(
        "По шаблону уже оформлены документы. Отключите его вместо удаления.",
      ),
    ).toBeInTheDocument();
    expect(readCompanyMock().docTemplates).toHaveLength(3);
  });

  it("шаблон письма: образец после сохранения и предупреждение про замену файлового", async () => {
    await openTab("templates");
    fireEvent.click(await screen.findByRole("tab", { name: "Письма" }));
    expect(await screen.findByText("invoice_issued")).toBeInTheDocument();
    await pickRowAction("quote_sent", "Изменить");
    const dialog = await screen.findByRole("region", { name: "Изменить шаблон письма" });
    fireEvent.click(within(dialog).getByLabelText("Шаблон действует"));
    expect(
      await within(dialog).findByText(/сразу заменит файловый для всех получателей/),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Показать образец" }));
    expect(await within(dialog).findByTitle("Образец письма")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().emailTemplates.find((t) => t.id === "2")?.is_active).toBe(true);
  });
});

describe("Справочники «Расчёта» на общем ресурсе (решение владельца 2026-11-11)", () => {
  it("добавление страны с кодом и скрытие валюты", async () => {
    await openTab("reference", "admin@demo.example");
    expect(await screen.findByText("Казахстан")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Добавить значение" }));
    const dialog = await screen.findByRole("region", { name: "Новое значение" });
    fireEvent.change(within(dialog).getByLabelText("Код"), { target: { value: "tr" } });
    fireEvent.change(within(dialog).getByLabelText("Название по-русски"), {
      target: { value: "Турция" },
    });
    fireEvent.change(within(dialog).getByLabelText("Название по-английски"), {
      target: { value: "Turkey" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Турция")).toBeInTheDocument();
    const turkey = readCompanyMock().reference.countries.find((c) => c.code === "TR");
    expect(turkey && (turkey as unknown as { name_en: string }).name_en).toBe("Turkey");

    fireEvent.click(screen.getByRole("link", { name: "Валюты" }));
    expect(await screen.findByText("Евро")).toBeInTheDocument();
    await pickRowAction("Евро", "Скрыть");
    await waitFor(() => {
      expect(readCompanyMock().reference.currencies.find((c) => c.code === "EUR")?.is_active).toBe(
        false,
      );
    });
  });

  it("строку, которую используют данные, удалить нельзя: сказано, что делать", async () => {
    await openTab("reference", "admin@demo.example");
    await pickRowAction("Узбекистан", "Удалить");
    const dialog = await screen.findByRole("dialog", { name: /Удалить/ });
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));
    expect(await screen.findByText(/можно только скрыть/)).toBeInTheDocument();
    expect(readCompanyMock().reference.countries.some((c) => c.code === "UZ")).toBe(true);
  });

  it("длинный список не одной страницей: поиск по названию и коду, страницы по 20", async () => {
    updateCompanyMock((state) => {
      for (let n = 4; n <= 120; n += 1) {
        const code = `X${String(n).padStart(3, "0")}`;
        state.reference.countries.push({
          id: String(n),
          code,
          name: `Страна ${code}`,
          alpha2: null,
          alpha3: null,
          iso_numeric: null,
          vat_rate: null,
          sort_order: n * 10,
          is_active: true,
          updated_at: "2026-10-27T10:00:00Z",
        } as never);
      }
    });
    await openTab("reference", "admin@demo.example");
    const region = await screen.findByRole("region", { name: "Страны" });
    expect(await within(region).findByText("Узбекистан")).toBeInTheDocument();
    expect(within(region).queryByText("Страна X120")).not.toBeInTheDocument();
    expect(document.querySelector(".ant-pagination")).not.toBeNull();

    fireEvent.change(screen.getByRole("searchbox", { name: "Поиск по коду и названию" }), {
      target: { value: "x120" },
    });
    expect(await within(region).findByText("Страна X120")).toBeInTheDocument();
    expect(within(region).queryByText("Узбекистан")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: "Поиск по коду и названию" }), {
      target: { value: "нет такой" },
    });
    // пусто — словами вместо таблицы (ListTable на DataTable, пункт «Т»)
    expect(await screen.findByText("Ничего не найдено")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Страны" })).toBeNull();
  });
});

describe("Категории и запросы", () => {
  it("добавление подкатегории и запрет удаления категории с подкатегориями", async () => {
    await openTab("categories");
    expect(await screen.findByText("Электрооборудование")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Подкатегория: добавить в «Электрооборудование»" }),
    );
    const dialog = await screen.findByRole("region", { name: "Новая категория" });
    fireEvent.change(within(dialog).getByLabelText("Название"), { target: { value: "Кабели" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Кабели")).toBeInTheDocument();
    expect(readCompanyMock().categories.find((c) => c.name === "Кабели")?.parent_id).toBe("5");

    fireEvent.click(screen.getByRole("button", { name: "Удалить: Подвижной состав" }));
    const confirm = await screen.findByRole("dialog", { name: /Удалить категорию/ });
    fireEvent.click(within(confirm).getByRole("button", { name: "Удалить" }));
    expect(
      await within(confirm).findByText(
        "У категории есть подкатегории. Сначала перенесите или удалите их.",
      ),
    ).toBeInTheDocument();
  });

  it("запросы: число на рассмотрении в подписи; отказ требует причину и объясняет последствия", async () => {
    await openTab("categories", "admin@demo.example");
    fireEvent.click(
      await screen.findByText("Запросы (2)", { selector: ".ant-segmented-item-label" }),
    );
    expect(await screen.findByText("Тормозные колодки")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Отклонить запрос: Тормозные колодки" }));
    const dialog = await screen.findByRole("dialog", { name: /Отклонить запрос/ });
    expect(within(dialog).getByRole("button", { name: "Отклонить" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Отклонить" }));
    expect(readCompanyMock().requests.find((r) => r.id === "2")?.status).toBe("pending");

    fireEvent.change(within(dialog).getByLabelText("Причина отказа"), {
      target: { value: "Дубль существующей категории" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Отклонить" }));
    expect(await screen.findByText("Запрос отклонён")).toBeInTheDocument();
    expect(readCompanyMock().requests.find((r) => r.id === "2")).toMatchObject({
      status: "rejected",
      review_notes: "Дубль существующей категории",
    });
    expect(
      await screen.findByText("Запросы (1)", { selector: ".ant-segmented-item-label" }),
    ).toBeInTheDocument();
  });

  it("запрос одобряют, выбрав заведённую категорию", async () => {
    await openTab("categories", "admin@demo.example");
    fireEvent.click(
      await screen.findByText("Запросы (2)", { selector: ".ant-segmented-item-label" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Одобрить запрос: Стрелочные переводы" }),
    );
    const dialog = await screen.findByRole("dialog", { name: /Одобрить запрос/ });

    fireEvent.mouseDown(within(dialog).getByLabelText("Категория, которую вы завели для запроса"));
    fireEvent.click(
      await screen.findByText("Крепёж", { selector: ".ant-select-item-option-content" }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Одобрить" }));

    expect(await screen.findByText("Запрос одобрен")).toBeInTheDocument();
    expect(readCompanyMock().requests.find((r) => r.id === "1")).toMatchObject({
      status: "approved",
      resulting_category_id: "2",
    });
  });

  it("решение директора ERP не принимает — понятный отказ в окне, запрос остаётся", async () => {
    await openTab("categories", "director@demo.example");
    fireEvent.click(
      await screen.findByText("Запросы (2)", { selector: ".ant-segmented-item-label" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Отклонить запрос: Тормозные колодки" }),
    );
    const dialog = await screen.findByRole("dialog", { name: /Отклонить запрос/ });
    fireEvent.change(within(dialog).getByLabelText("Причина отказа"), { target: { value: "Нет" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Отклонить" }));
    expect(readCompanyMock().requests.find((r) => r.id === "2")?.status).toBe("pending");
  });
});

describe("Платформенные настройки", () => {
  it("«Налоги и валюты»: ставка НДС — одно поле (в новом КП), курс вводится одной формой (ЕВ-0)", async () => {
    await openTab("platform", "director@demo.example");
    expect(await screen.findByLabelText("Ставка НДС в новом КП, %")).toBeInTheDocument();
    // адрес поддержки — контакт компании: на «Реквизитах и бланке», здесь его нет (ЕВ-2а, стр. 12)
    expect(screen.queryByLabelText("Адрес поддержки")).toBeNull();
    // второго поля, которое расчёт не читает, нет
    expect(screen.getAllByLabelText(/Ставка НДС/)).toHaveLength(1);
    // ручной ввод курса — форма «Курс валюты к суму»; кнопки «Ввести курс USD» у списка курсов нет
    expect(await screen.findByRole("form", { name: "Ручной ввод курса" })).toBeInTheDocument();
    expect(screen.getAllByRole("form", { name: /курс/i })).toHaveLength(1);
    await screen.findAllByText("Вручную");
    expect(screen.queryByRole("button", { name: "Ввести курс USD" })).toBeNull();
    expect(screen.getAllByRole("button", { name: /Сохранить курс|Ввести курс/ })).toHaveLength(1);
  });

  it("директору ERP адрес поддержки менять не даёт — отказ словами, адрес прежний", async () => {
    await openTab("details", "director@demo.example");
    const field = await screen.findByLabelText("Адрес поддержки");
    fireEvent.change(field, { target: { value: "help@rt.uz" } });
    fireEvent.click(await button("Сохранить настройки"));
    // дождаться отказа: иначе ответ придёт уже в следующем тесте
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(readCompanyMock().platform.support_email).toBe("");
  });

  it("адрес поддержки задаётся здесь; неверный адрес — сообщение у поля (СЦ-3)", async () => {
    await openTab("details", "admin@demo.example");
    const field = await screen.findByLabelText("Адрес поддержки");
    expect(field).toHaveValue("");
    fireEvent.change(field, { target: { value: "help" } });
    fireEvent.click(await button("Сохранить настройки"));
    expect(await screen.findByText("Введите адрес почты")).toBeInTheDocument();
    expect(readCompanyMock().platform.support_email).toBe("");

    fireEvent.change(field, { target: { value: " help@rt.uz " } });
    fireEvent.click(await button("Сохранить настройки"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().platform.support_email).toBe("help@rt.uz");
    expect(readCompanyMock().platform.vat_rate).toBe("12.00");
  });
});

describe("Курс USD → UZS: ручной ввод", () => {
  const today = () => companyDayKey(new Date()) ?? "";

  function readerOfSettings() {
    writeRoles([
      ...readRoles(),
      {
        id: "50",
        name: "Читатель настроек",
        description: "",
        system: false,
        version: 1,
        access: { "dashboard.queue": "full", "company.settings": "read" },
        restricted_fields: [],
        updated_at: "2026-10-26T00:00:00.000Z",
      },
    ]);
    writeEmployees(
      readEmployees().map((e) => (e.id === "u-demo-manager" ? { ...e, role_ids: ["50"] } : e)),
    );
  }

  it("показывает текущий курс, его дату и источник и журнал", async () => {
    await openTab("platform", "admin@demo.example");
    const section = within(await screen.findByRole("region", { name: "Курс валюты к суму" }));
    expect(await section.findByText(/1 USD = 12\s650,50 сум/)).toBeInTheDocument();
    expect(section.getByText("26.10.2026")).toBeInTheDocument();
    expect(section.getByText("Автозагрузка (ЦБ РУз)")).toBeInTheDocument();
    const journal = within(section.getByRole("region", { name: "Журнал курса" }));
    expect(journal.getByText("Ввод вручную")).toBeInTheDocument();
    expect(journal.getByText("Автокурс ЦБ не применён")).toBeInTheDocument();
    expect(journal.getByText("Демо Директоров")).toBeInTheDocument();
    expect(journal.getByText("Автозагрузка")).toBeInTheDocument();
    expect(screen.getByLabelText("Дата курса")).toHaveValue(today().split("-").reverse().join("."));
  });

  it("курс любой включённой валюты (пункт 1.7): выбор валюты, ввод, курс этой валюты", async () => {
    await openTab("platform", "admin@demo.example");
    const select = await screen.findByLabelText("Валюта");
    fireEvent.mouseDown(select);
    fireEvent.click(await screen.findByText("EUR — Евро"));
    const rate = await screen.findByLabelText("Курс, сум за 1 EUR");
    fireEvent.change(rate, { target: { value: "14000" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить курс" }));
    expect(await screen.findByText("Курс сохранён")).toBeInTheDocument();
    expect(await screen.findByText(/1 EUR = 14\s000,00 сум/)).toBeInTheDocument();
    expect(readCompanyMock().fxOthers?.EUR?.current?.rate_to_uzs).toBe("14000");
    expect(readCompanyMock().fx.current?.rate_to_uzs).toBe("12650.5"); // курс USD не тронут
  });

  it("вводит курс запятой: курс, источник и журнал обновляются, поле очищается", async () => {
    await openTab("platform", "admin@demo.example");
    const rate = await screen.findByLabelText("Курс, сум за 1 USD");
    fireEvent.change(rate, { target: { value: "12700,5" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить курс" }));
    expect(await screen.findByText("Курс сохранён")).toBeInTheDocument();
    expect(await screen.findByText(/1 USD = 12\s700,50 сум/)).toBeInTheDocument();
    expect(screen.getByText("Введён вручную", { selector: ".ant-tag" })).toBeInTheDocument();
    expect(rate).toHaveValue("");
    const saved = readCompanyMock().fx;
    expect(saved.current).toEqual({
      rate_to_uzs: "12700.5",
      rate_date: today(),
      source: "manual",
    });
    expect(saved.journal[0]).toMatchObject({ kind: "manual", rate_to_uzs: "12700.5" });
    expect(readCompanyMock().platform.exchange_rate_usd_uzs).toBe("12700.5");
  });

  it.each(["0", "-5", "abc", "12700,1234567"])(
    "курс «%s» не уходит на сервер: ошибка у поля словами",
    async (value) => {
      await openTab("platform", "admin@demo.example");
      const rate = await screen.findByLabelText("Курс, сум за 1 USD");
      const before = readCompanyMock().fx.journal.length;
      fireEvent.change(rate, { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "Сохранить курс" }));
      expect(await screen.findByText(/Курс — число больше нуля/)).toBeInTheDocument();
      expect(rate).toHaveAttribute("aria-invalid", "true");
      expect(readCompanyMock().fx.journal).toHaveLength(before);
    },
  );

  it("дата позже сегодняшней не выбирается: в календаре дни после сегодня отключены", async () => {
    await openTab("platform", "admin@demo.example");
    const date = await screen.findByLabelText("Дата курса");
    fireEvent.mouseDown(date);
    fireEvent.click(date);
    const cell = (day: string) =>
      document.querySelector<HTMLElement>(`.ant-picker-cell[title="${day}"]`);
    await waitFor(() => {
      expect(cell(today())).not.toHaveClass("ant-picker-cell-disabled");
    });
    const [y = 0, m = 1, d = 1] = today().split("-").map(Number);
    const tomorrow = new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
    expect(cell(tomorrow)).toHaveClass("ant-picker-cell-disabled");
  });

  it("дата позже сегодняшней — ошибка у поля даты, запись не создаётся", async () => {
    await openTab("platform", "admin@demo.example");
    const before = readCompanyMock().fx.journal.length;
    fillDate(await screen.findByLabelText("Дата курса"), "2099-01-01");
    fireEvent.change(screen.getByLabelText("Курс, сум за 1 USD"), { target: { value: "12700" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить курс" }));
    expect(
      await screen.findByText("Дата курса не может быть позже сегодняшней."),
    ).toBeInTheDocument();
    expect(readCompanyMock().fx.journal).toHaveLength(before);
  });

  it("отказ сервера по полю показывается у этого поля", async () => {
    server.use(
      http.post("*/admin/company/fx-rate", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "Проверьте заполнение полей.",
            source: "erp",
            details: { fields: ["rate_date"], reason: "fx_rate_date_too_old" },
          },
          { status: 422 },
        ),
      ),
    );
    await openTab("platform", "admin@demo.example");
    fireEvent.change(await screen.findByLabelText("Курс, сум за 1 USD"), {
      target: { value: "12700" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить курс" }));
    expect(await screen.findByText(/старше года не вводится/)).toBeInTheDocument();
    expect(screen.getByLabelText("Дата курса")).toHaveAttribute("aria-invalid", "true");
  });

  it("отказ ERP по правам — словами над кнопкой, курс прежний", async () => {
    server.use(
      http.post("*/admin/company/fx-rate", () =>
        HttpResponse.json({ code: "FORBIDDEN", message: "нет", source: "erp" }, { status: 403 }),
      ),
    );
    await openTab("platform", "admin@demo.example");
    fireEvent.change(await screen.findByLabelText("Курс, сум за 1 USD"), {
      target: { value: "12700" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить курс" }));
    expect(await screen.findByText(/1 USD = 12\s650,50 сум/)).toBeInTheDocument();
  });

  it("журнал недоступен без права ERP: курс виден, секции журнала нет (W15-H8)", async () => {
    server.use(
      http.get("*/admin/company/fx-rate", () =>
        HttpResponse.json({
          currency: "USD",
          currencies: [{ code: "USD", name: "Доллар США" }],
          current: { rate_to_uzs: "12650.5", rate_date: "2026-10-27", source: "auto" },
          max_age_days: 7,
          journal: [],
          journal_available: false,
        }),
      ),
    );
    await openTab("platform", "director@demo.example");
    expect(await screen.findByText(/1 USD = 12\s650,50 сум/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Журнал курса" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Журнал курса" })).not.toBeInTheDocument();
    expect(screen.queryByText("Ручных вводов пока не было")).not.toBeInTheDocument();
  });

  it("нет свежего курса — предупреждение со сроком и приглашением ввести курс", async () => {
    updateCompanyMock((state) => {
      state.fx.current = null;
    });
    await openTab("platform", "admin@demo.example");
    expect(await screen.findByText(/Свежего курса нет/)).toBeInTheDocument();
    expect(screen.getByText(/за последние 7 дн/)).toBeInTheDocument();
  });

  it("журнал пуст — слово и пояснение, а не пустая таблица", async () => {
    updateCompanyMock((state) => {
      state.fx.journal = [];
    });
    await openTab("platform", "admin@demo.example");
    expect(
      await screen.findByRole("heading", { name: "Ручных вводов пока не было" }),
    ).toBeInTheDocument();
  });

  it("доступ «чтение»: курс и журнал видны, поля и «Сохранить курс» заблокированы", async () => {
    readerOfSettings();
    await openTab("platform", "manager@demo.example");
    expect(await screen.findByText(/1 USD = 12\s650,50 сум/)).toBeInTheDocument();
    expect(screen.getByLabelText("Дата курса")).toBeDisabled();
    expect(screen.getByLabelText("Курс, сум за 1 USD")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Сохранить курс" })).toBeDisabled();
    expect(screen.getByText("Ввод вручную")).toBeInTheDocument();
  });
});

describe("Admin · Компания: страна на языке интерфейса (план справочников, PR 6)", () => {
  it("страна регистрации — на языке интерфейса: «Узбекистан», «O‘zbekiston», «Uzbekistan»", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/company?tab=details");
    expect(await screen.findByText("Узбекистан")).toBeVisible();
    await act(() => i18n.changeLanguage("uz"));
    expect(await screen.findByText("O‘zbekiston")).toBeVisible();
    await act(() => i18n.changeLanguage("en"));
    expect(await screen.findByText("Uzbekistan")).toBeVisible();
    expect(screen.queryByText("Узбекистан")).not.toBeInTheDocument();
  });
});
