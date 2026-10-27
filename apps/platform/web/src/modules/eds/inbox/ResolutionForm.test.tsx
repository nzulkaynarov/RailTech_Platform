import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { companyDate } from "./api";
import { panelEl, renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";

setupLetterTests();

const LETTER = "/eds/inbox/%D0%92%D0%A5-104%2F26";

async function openForm(path = LETTER, directoryReady = true) {
  signIn("director@demo.example");
  const view = renderAt(path);
  const panel = await panelEl();
  const form = await within(panel).findByRole("form", { name: "Резолюция директора" });
  // справочник сотрудников загружен: зона «услуги» с одним кандидатом выбрана сама
  if (directoryReady) {
    await waitFor(() => {
      expect(within(form).getByLabelText("Сотрудник: Гл. инженер")).toHaveValue("41");
    });
  }
  return { ...view, panel, form };
}

function draftKeys(): string[] {
  return Object.keys(window.localStorage).filter((k) => k.startsWith("rt-pf-letter-draft-v1"));
}

function fillValid(form: HTMLElement) {
  fireEvent.change(within(form).getByLabelText("Текст резолюции"), {
    target: { value: "Посчитать с запасом по складу." },
  });
  fireEvent.change(within(form).getByLabelText("Сотрудник: Снабженец"), {
    target: { value: "31" },
  });
}

describe("Резолюция: форма", () => {
  it("поля, подписи зон, бухгалтер выключен, один кандидат выбран сам, «Что произойдёт»", async () => {
    const { form } = await openForm();

    expect(within(form).getByLabelText("Текст резолюции")).toBeVisible();
    const supply = within(form).getByRole("checkbox", {
      name: /Снабженец.*склад и цены поставщиков/,
    });
    const engineer = within(form).getByRole("checkbox", {
      name: /Гл\. инженер.*услуги, ТЗ, бригада/,
    });
    const accountant = within(form).getByRole("checkbox", { name: /Бухгалтер.*условия оплаты/ });
    expect(supply).toBeChecked();
    expect(engineer).toBeChecked();
    expect(accountant).not.toBeChecked();
    // в «товарах» двое — выбор за директором; в «услугах» один — выбран сам
    expect(within(form).getByLabelText("Сотрудник: Снабженец")).toHaveValue("");
    expect(within(form).getByLabelText("Сотрудник: Гл. инженер")).toHaveValue("41");
    expect(within(form).getByLabelText("Срок расчёта")).toHaveValue(companyDate(3));
    expect(within(form).getByLabelText("Маржа не ниже, %")).toBeVisible();
    const consequence = within(form).getByRole("group", { name: "Что произойдёт" });
    expect(within(consequence).getAllByRole("listitem")).toHaveLength(3);
    expect(within(consequence).getByText(/Клиенту ничего не отправляется/)).toBeVisible();
    expect(
      within(form).getByRole("button", { name: "Утвердить резолюцию → задание в расчёт" }),
    ).toBeEnabled();
  });

  it("«Вернуть менеджеру» и «Отклонить» неактивны с подписью, пока нет комментария", async () => {
    const { form } = await openForm();
    const back = within(form).getByRole("button", { name: "Вернуть менеджеру" });
    const reject = within(form).getByRole("button", { name: "Отклонить" });

    expect(back).toBeDisabled();
    expect(reject).toBeDisabled();
    expect(back).toHaveAccessibleDescription(/Кнопки неактивны, пока нет комментария/);

    fireEvent.change(within(form).getByLabelText("Комментарий"), { target: { value: "  " } });
    expect(back).toBeDisabled();

    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Нужны сроки" },
    });
    expect(back).toBeEnabled();
    expect(reject).toBeEnabled();
    expect(within(form).queryByText(/Кнопки неактивны/)).toBeNull();
  });

  it("пустая форма: подсказки у полей, запрос не уходит", async () => {
    let called = false;
    server.use(
      http.post("*/eds/letters/:id/resolution", () => {
        called = true;
        return HttpResponse.json({});
      }),
    );
    const { form } = await openForm();

    fireEvent.click(within(form).getByRole("button", { name: /Утвердить резолюцию/ }));

    expect(await within(form).findByText("Напишите текст резолюции.")).toBeVisible();
    expect(within(form).getByText("Выберите сотрудника.")).toBeVisible();
    expect(within(form).getByLabelText("Текст резолюции")).toHaveAttribute("aria-invalid", "true");
    expect(called).toBe(false);
  });

  it("срок в прошлом и неверная маржа отсекаются в форме", async () => {
    const { form } = await openForm();
    fillValid(form);
    fireEvent.change(within(form).getByLabelText("Срок расчёта"), {
      target: { value: "2020-01-01" },
    });
    fireEvent.change(within(form).getByLabelText("Маржа не ниже, %"), { target: { value: "120" } });

    fireEvent.click(within(form).getByRole("button", { name: /Утвердить резолюцию/ }));

    expect(await within(form).findByText("Срок расчёта не может быть в прошлом.")).toBeVisible();
    expect(
      within(form).getByText("Маржа — число от 0 до 100, не больше двух знаков после запятой."),
    ).toBeVisible();
  });

  it("«Утвердить»: тело запроса, письмо получает статус «Резолюция наложена», черновик стёрт", async () => {
    let sent: unknown;
    server.use(
      http.post("*/eds/letters/:id/resolution", async ({ request, params }) => {
        sent = await request.clone().json();
        sent = { id: params["id"], ...(sent as object) };
        return undefined;
      }),
    );
    const { form, panel } = await openForm();
    fillValid(form);
    fireEvent.change(within(form).getByLabelText("Маржа не ниже, %"), {
      target: { value: "15,5" },
    });
    expect(draftKeys()).toHaveLength(1);

    fireEvent.click(within(form).getByRole("button", { name: /Утвердить резолюцию/ }));

    expect(await screen.findByText("Резолюция наложена: задание ушло исполнителям")).toBeVisible();
    expect(sent).toEqual({
      id: "20000000-0000-4000-8000-000000000104",
      text: "Посчитать с запасом по складу.",
      assignees: [
        { id: "31", zone: "goods" },
        { id: "41", zone: "services" },
      ],
      due: companyDate(3),
      min_margin_pct: "15.5",
    });
    expect(
      await within(panel).findByRole("heading", { name: "Решение по письму принято" }),
    ).toBeVisible();
    expect(await screen.findByRole("heading", { name: "Решение директора" })).toBeVisible();
    expect(screen.getByText("15.5 %")).toBeVisible();
    expect(draftKeys()).toHaveLength(0);
  });

  it("«Вернуть менеджеру» с комментарием", async () => {
    const { form, panel } = await openForm();
    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Нужен объём" },
    });

    fireEvent.click(within(form).getByRole("button", { name: "Вернуть менеджеру" }));

    expect(
      await screen.findByText("Письмо возвращено менеджеру", {
        selector: ".ant-message-notice-content *",
      }),
    ).toBeVisible();
    expect(
      await within(panel).findByRole("heading", { name: "Решение по письму принято" }),
    ).toBeVisible();
    expect((await screen.findAllByText("Нужен объём")).length).toBeGreaterThan(0);
  });

  it("«Отклонить» с причиной: статус «Отклонено», на шкале «Отказ»", async () => {
    const { form } = await openForm();
    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Не наш профиль" },
    });

    fireEvent.click(within(form).getByRole("button", { name: "Отклонить" }));

    expect(await screen.findByText("Не наш профиль")).toBeVisible();
    await waitFor(() => {
      expect(screen.getAllByText("Отклонено").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("Отказ").length).toBeGreaterThan(0);
  });
});

describe("Резолюция: ошибки и черновик", () => {
  it("срок в прошлом отвергнут EDS: «Резолюция не сохранена: …», введённое не потеряно, черновик в браузере", async () => {
    const { form } = await openForm();
    fillValid(form);
    // форма сама отсекает прошлую дату, поэтому подменяем «сегодня» EDS: он считает срок прошлым
    server.use(
      http.post("*/eds/letters/:id/resolution", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "Срок расчёта не может быть в прошлом.",
            source: "eds",
            details: { fields: ["due"], reason: "due_in_past", backend_status: 422 },
          },
          { status: 422 },
        ),
      ),
    );

    fireEvent.click(within(form).getByRole("button", { name: /Утвердить резолюцию/ }));

    expect(
      await within(form).findByText(
        "Резолюция не сохранена: срок расчёта в прошлом. Текст сохранён в черновике.",
      ),
    ).toBeVisible();
    expect(within(form).getByLabelText("Текст резолюции")).toHaveValue(
      "Посчитать с запасом по складу.",
    );
    expect(within(form).getByLabelText("Сотрудник: Снабженец")).toHaveValue("31");
    // поле срока подсвечено словами
    expect(within(form).getByText("Срок расчёта не может быть в прошлом.")).toBeVisible();
    const [key] = draftKeys();
    expect(key).toBeDefined();
    expect(JSON.parse(window.localStorage.getItem(key ?? "") ?? "{}")).toMatchObject({
      text: "Посчитать с запасом по складу.",
    });
  });

  it("EDS недоступен: причина словами, текст остаётся; после перезагрузки страницы черновик восстановлен", async () => {
    server.use(
      http.post("*/eds/letters/:id/resolution", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "Сервис временно недоступен.", source: "eds" },
          { status: 503 },
        ),
      ),
    );
    const first = await openForm();
    fillValid(first.form);
    fireEvent.click(within(first.form).getByRole("button", { name: /Утвердить резолюцию/ }));
    expect(
      await within(first.form).findByText(
        "Резолюция не сохранена: документооборот не отвечает. Текст сохранён в черновике.",
      ),
    ).toBeVisible();
    expect(within(first.form).getByLabelText("Текст резолюции")).toHaveValue(
      "Посчитать с запасом по складу.",
    );

    // закрыли вкладку и открыли письмо снова
    cleanup();
    const second = await openForm();
    expect(second.form).toHaveTextContent("Восстановлен черновик, который вы не отправили.");
    expect(within(second.form).getByLabelText("Текст резолюции")).toHaveValue(
      "Посчитать с запасом по складу.",
    );
    expect(within(second.form).getByLabelText("Сотрудник: Снабженец")).toHaveValue("31");
  });

  it("письмо уже решено другим (409): объяснение «обновите карточку», комментарий возврата в черновике", async () => {
    server.use(
      http.post("*/eds/letters/:id/return", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "Операция недоступна в текущем статусе письма.",
            source: "eds",
            details: { reason: "invalid_state", backend_status: 409 },
          },
          { status: 409 },
        ),
      ),
    );
    const { form } = await openForm();
    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Нужен объём" },
    });

    fireEvent.click(within(form).getByRole("button", { name: "Вернуть менеджеру" }));

    expect(
      await within(form).findByText(
        "Письмо не возвращено: письмо уже не ждёт резолюции, обновите карточку. Комментарий сохранён в черновике.",
      ),
    ).toBeVisible();
    expect(within(form).getByLabelText("Комментарий")).toHaveValue("Нужен объём");
  });

  it("исполнитель отключён (422 по полю assignees) — подсвечена зона исполнителей", async () => {
    server.use(
      http.post("*/eds/letters/:id/resolution", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "Исполнитель не найден или отключён.",
            source: "eds",
            details: { fields: ["assignees"], reason: "not_active_employee", backend_status: 422 },
          },
          { status: 422 },
        ),
      ),
    );
    const { form } = await openForm();
    fillValid(form);

    fireEvent.click(within(form).getByRole("button", { name: /Утвердить резолюцию/ }));

    expect(await within(form).findByText("Отметьте хотя бы одного исполнителя.")).toBeVisible();
    expect(
      within(form).getByText(
        "Резолюция не сохранена: исполнитель не найден или отключён. Текст сохранён в черновике.",
      ),
    ).toBeVisible();
  });

  it("справочник сотрудников недоступен роли: объяснение, главная кнопка неактивна, возврат и отказ работают", async () => {
    server.use(
      http.get("*/eds/resolution/assignees", () =>
        HttpResponse.json({
          zones: [
            { zone: "goods", candidates: [] },
            { zone: "services", candidates: [] },
            { zone: "payment_terms", candidates: [] },
          ],
          directory: "forbidden",
        }),
      ),
    );
    const { form } = await openForm(LETTER, false);

    expect(await within(form).findByText(/Выбор исполнителей недоступен/)).toBeVisible();
    expect(within(form).getByRole("button", { name: /Утвердить резолюцию/ })).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Ждём админа" },
    });
    expect(within(form).getByRole("button", { name: "Вернуть менеджеру" })).toBeEnabled();
  });
});
