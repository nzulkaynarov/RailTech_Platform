import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
import i18n from "../../../shared/i18n";
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

async function openTab(tab: string, email = "director@demo.example") {
  signInAs(email);
  renderApp(`/admin/company?tab=${tab}`);
  await screen.findByRole("heading", { level: 1, name: "Компания" });
}

const button = (name: string | RegExp) => screen.findByRole("button", { name });

function type(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("Admin · Компания: доступ и каркас", () => {
  it("директор и администратор открывают раздел; заголовок и подзаголовок — название компании", async () => {
    await openTab("details", "admin@demo.example");
    expect(await screen.findByText("ООО «Демо Рейл»", { selector: "div" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Реквизиты" })).toHaveAttribute("aria-selected", "true");
    for (const name of [
      "Бланк и бренд",
      "Нумерация",
      "Условия КП",
      "Статьи расхода",
      "Шаблоны",
      "Справочники",
      "Категории",
      "Платформа",
    ]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }
  });

  it("без раздела `company.settings` пункт «Компания» скрыт в меню, а прямой адрес даёт «Нет доступа»", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/company");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Нет доступа" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Компания" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Реквизиты" })).toBeNull();
  });

  it("администратор видит пункт «Компания» в меню Admin", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org");
    expect(await screen.findByRole("link", { name: "Компания" })).toBeInTheDocument();
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
      await screen.findByRole("heading", { name: "Своя компания в ERP ещё не создана" }),
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
    expect(screen.getByRole("button", { name: "Сохранить реквизиты" })).toBeDisabled();
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

    fireEvent.click(screen.getByRole("tab", { name: "Бланк и бренд" }));
    expect(screen.getByRole("tab", { name: "Бланк и бренд" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByLabelText("Подписант")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Сохранить бланк" })).toBeDisabled();
    await screen.findByTitle("Образец: КП");
    fireEvent.click(screen.getByText("Договор", { selector: ".ant-segmented-item-label" }));
    await waitFor(() => {
      expect(screen.getByTitle("Образец: Договор").getAttribute("srcdoc")).toContain(
        "Договор поставки",
      );
    });

    fireEvent.click(screen.getByRole("tab", { name: "Шаблоны" }));
    fireEvent.click(await screen.findByRole("button", { name: "Открыть: Договор поставки (наш)" }));
    const viewer = await screen.findByRole("dialog", { name: "Шаблон документа" });
    expect(within(viewer).getByLabelText(/^Текст шаблона/)).toBeDisabled();
    expect(within(viewer).queryByRole("button", { name: "Сохранить" })).toBeNull();
    expect(await within(viewer).findByTitle("Образец документа по шаблону")).toBeInTheDocument();
    fireEvent.click(within(viewer).getByRole("button", { name: "Закрыть" }));
    expect(screen.getByRole("button", { name: "Создать шаблон" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /^Изменить:/ })).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Справочники" }));
    expect(await screen.findByText("Казахстан")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить строку" })).toBeDisabled();
    fireEvent.click(screen.getByText("Валюты", { selector: ".ant-segmented-item-label" }));
    expect(await screen.findByText("Евро")).toBeInTheDocument();
  });
});

describe("Реквизиты и логотип", () => {
  it("правка телефона: «Сохранить» активна только при изменении, в ERP уходит одно поле", async () => {
    await openTab("details");
    const save = await button("Сохранить реквизиты");
    expect(save).toBeDisabled();

    type("Телефон", "+998 11 111 11 11");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Сохранить реквизиты" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить реквизиты" }));

    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().company.phone).toBe("+998 11 111 11 11");
    expect(readCompanyMock().company.name).toBe("ООО «Демо Рейл»");
    expect(
      screen.getByText(/Реквизиты обновятся в карточке своей компании в ERP/),
    ).toBeInTheDocument();
  });

  it("неверный ИНН: сообщение у поля, запрос не уходит", async () => {
    await openTab("details");
    await screen.findByLabelText(/^ИНН/);
    type(/^ИНН/, "12");
    fireEvent.click(await button("Сохранить реквизиты"));

    expect(await screen.findByText("ИНН — 9 цифр")).toBeInTheDocument();
    expect(readCompanyMock().company.inn).toBe("123456789");
  });

  it("логотип: загрузка файла и удаление", async () => {
    await openTab("details");
    const input = await screen.findByLabelText("Выбрать файл: Логотип компании");
    expect(screen.getByText("Нет логотипа")).toBeInTheDocument();
    const seen = stubLogoUpload("/admin/company/logo");

    const file = new File(["png"], "logo.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText("Логотип загружен")).toBeInTheDocument();
    expect(seen).toEqual([{ name: "logo.png", type: "image/png" }]);
    expect(readCompanyMock().company.logo_url).toMatch(/^data:image/);
    fireEvent.click(await button("Удалить логотип"));
    const confirm = await screen.findByRole("dialog", { name: "Удалить логотип компании?" });
    expect(within(confirm).getByText("Что произойдёт")).toBeInTheDocument();
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
      expect(within(list).getByText(/DEMO-КП-\d{4}-00001/)).toBeInTheDocument();
    });

    type("Префикс нумерации", "ACME");
    await waitFor(() => {
      expect(screen.getByText(/ACME-КП-\d{4}-00001/)).toBeInTheDocument();
    });
    expect(readCompanyMock().numbering.prefix).toBe("DEMO");
  });

  it("маска без {seq}: сохранить нельзя, образца нет", async () => {
    await openTab("numbering");
    await screen.findByLabelText("Маска номера");
    type("Маска номера", "{type}-");
    expect(await screen.findByText("В маске обязателен токен {seq}")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить нумерацию" })).toBeDisabled();
    expect(screen.getByText(/Укажите корректную маску/)).toBeInTheDocument();
  });

  it("сохранение: схема в ERP, «Что произойдёт» говорит про будущие номера", async () => {
    await openTab("numbering");
    await screen.findByLabelText("Ширина счётчика");
    fireEvent.change(screen.getByLabelText("Ширина счётчика"), { target: { value: "6" } });
    expect(screen.getByText("Новые номера пойдут по этой схеме.")).toBeInTheDocument();
    expect(screen.getByText("Уже выданные номера не меняются.")).toBeInTheDocument();
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

  it("пустой префикс: подсказка, что своя схема без него не действует", async () => {
    await openTab("numbering");
    await screen.findByLabelText("Префикс нумерации");
    type("Префикс нумерации", "");
    expect(await screen.findByText(/Своя схема действует только с префиксом/)).toBeInTheDocument();
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

describe("Статьи расхода", () => {
  it("список по базисам, изменение суммы и удаление с блоком «Что произойдёт»", async () => {
    await openTab("charges");
    expect(await screen.findByText("Страхование груза")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Изменить: Фрахт · FCA" }));
    const dialog = await screen.findByRole("dialog", { name: "Изменить статью расхода" });
    fireEvent.change(within(dialog).getByLabelText("Сумма"), { target: { value: "1800" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().charges[0]?.default_amount).toBe("1800");

    fireEvent.click(
      await screen.findByRole("button", { name: "Удалить: Таможенное оформление · DAP" }),
    );
    const confirm = await screen.findByRole("dialog", { name: /Удалить статью/ });
    expect(within(confirm).getByText("Что произойдёт")).toBeInTheDocument();
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
    fireEvent.click(
      screen.getByRole("button", { name: "Скопировать к себе: Образец: договор поставки" }),
    );
    const dialog = await screen.findByRole("dialog", { name: /Скопировать/ });
    expect(within(dialog).getByLabelText("Название")).toHaveValue(
      "Образец: договор поставки (копия)",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Скопировать к себе" }));
    expect(await screen.findByText("Копия создана")).toBeInTheDocument();
    expect(readCompanyMock().docTemplates.filter((t) => t.is_owned)).toHaveLength(3);
  });

  it("редактор документа: подстановки, образец в рамке и предупреждение об неизвестной подстановке", async () => {
    await openTab("templates");
    fireEvent.click(await screen.findByRole("button", { name: "Изменить: Акт приёмки" }));
    const dialog = await screen.findByRole("dialog", { name: "Изменить шаблон документа" });
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

  it("шаблон, по которому уже оформлены документы, удалить нельзя — слова, а не код", async () => {
    await openTab("templates");
    fireEvent.click(await screen.findByRole("button", { name: "Удалить: Договор поставки (наш)" }));
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
    fireEvent.click(
      await screen.findByText("Шаблоны писем", { selector: ".ant-segmented-item-label" }),
    );
    expect(await screen.findByText("invoice_issued")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Изменить: quote_sent" }));
    const dialog = await screen.findByRole("dialog", { name: "Изменить шаблон письма" });
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

describe("Справочники", () => {
  it("добавление страны и отключение валюты", async () => {
    await openTab("reference");
    expect(await screen.findByText("Казахстан")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Добавить строку" }));
    const dialog = await screen.findByRole("dialog", { name: "Новая строка справочника" });
    fireEvent.change(within(dialog).getByLabelText("Код"), { target: { value: "TR" } });
    fireEvent.change(within(dialog).getByLabelText("Название"), { target: { value: "Турция" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Турция")).toBeInTheDocument();
    expect(readCompanyMock().reference.countries.map((c) => c.code)).toContain("TR");

    fireEvent.click(screen.getByText("Валюты", { selector: ".ant-segmented-item-label" }));
    expect(await screen.findByText("Евро")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Отключить: Евро" }));
    await waitFor(() => {
      expect(readCompanyMock().reference.currencies.find((c) => c.code === "EUR")?.is_active).toBe(
        false,
      );
    });
  });

  it("строку, которую используют документы, удалить нельзя: сказано, что делать", async () => {
    await openTab("reference");
    fireEvent.click(await screen.findByRole("button", { name: "Удалить: Узбекистан" }));
    const dialog = await screen.findByRole("dialog", { name: /Удалить/ });
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));
    expect(
      await within(dialog).findByText(
        "Строка используется в документах и данных. Отключите её вместо удаления.",
      ),
    ).toBeInTheDocument();
    expect(readCompanyMock().reference.countries).toHaveLength(3);
  });

  it("сказано, каких справочников в Платформе пока нет", async () => {
    await openTab("reference");
    expect(await screen.findByText(/Курсы валют, коды ТН ВЭД и производители/)).toBeInTheDocument();
  });
});

describe("Категории и запросы", () => {
  it("добавление подкатегории и запрет удаления категории с подкатегориями", async () => {
    await openTab("categories");
    expect(await screen.findByText("Электрооборудование")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Подкатегория: добавить в «Электрооборудование»" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Новая категория" });
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
    expect(within(dialog).getByText("Что произойдёт")).toBeInTheDocument();
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
    expect(
      within(dialog).getByText(/Сама категория в каталоге этим действием не создаётся/),
    ).toBeInTheDocument();

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
    expect(await within(dialog).findByText(/ERP не разрешила действие/)).toBeInTheDocument();
    expect(readCompanyMock().requests.find((r) => r.id === "2")?.status).toBe("pending");
  });
});

describe("Платформенные настройки", () => {
  it("администратор меняет ставку НДС; курс только для чтения", async () => {
    await openTab("platform", "admin@demo.example");
    const vat = await screen.findByLabelText("Ставка НДС, %");
    expect(vat).toHaveDisplayValue(/^12/);
    expect(screen.getByText(/1 USD = 12\s650,50 сум/)).toBeInTheDocument();
    fireEvent.change(vat, { target: { value: "15" } });
    fireEvent.click(await button("Сохранить ставку НДС"));
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
    expect(readCompanyMock().platform.vat_rate).toBe("15.00");
  });

  it("директору ERP ставку менять не даёт — отказ словами, ставка прежняя", async () => {
    await openTab("platform", "director@demo.example");
    const vat = await screen.findByLabelText("Ставка НДС, %");
    fireEvent.change(vat, { target: { value: "15" } });
    fireEvent.click(await button("Сохранить ставку НДС"));
    expect(await screen.findByText(/ERP не разрешила действие/)).toBeInTheDocument();
    expect(readCompanyMock().platform.vat_rate).toBe("12.00");
  });
});
