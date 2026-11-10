import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import type { LetterRegisterIn } from "../../../shared/api/generated/model";
import { chooseOption, selectedLabel } from "../../../test/fields";
import { setupLetterTests } from "../../../test/lettersKit";
import { renderAt, signIn } from "../../../test/edsKit";
import { server } from "../../../test/server";
import { readDictionaries, writeDictionaries } from "../../../mocks/dictionaries";
import { resetEds } from "../../../mocks/fixtures/edsDocuments";
import { emptyRegister, toRegisterBody, validateRegister } from "./registerModel";

setupLetterTests();

const TITLE = "Зарегистрировать входящее";

async function openForm(email = "registrar@demo.example") {
  resetEds();
  signIn(email);
  renderAt("/eds/register");
  expect(await screen.findByRole("heading", { level: 1, name: TITLE })).toBeVisible();
}

function type(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

async function attach() {
  fireEvent.change(screen.getByLabelText("Файл документа"), {
    target: { files: [new File(["%PDF-1.4"], "trebovanie.pdf", { type: "application/pdf" })] },
  });
  const list = await screen.findByRole("list", { name: "Прикреплённые файлы" });
  expect(await within(list).findByText("загружен")).toBeVisible();
}

describe("EDS · Зарегистрировать входящее (P8)", () => {
  it("делопроизводитель видит кнопку «Зарегистрировать входящее» во «Входящих письмах»", async () => {
    signIn("registrar@demo.example");
    renderAt("/eds/inbox");
    expect(await screen.findByRole("link", { name: TITLE })).toHaveAttribute(
      "href",
      "/eds/register",
    );
  });

  it("без обязательных полей запрос не уходит: тексты у полей", async () => {
    let sent = false;
    server.use(
      http.post("*/eds/letters", () => {
        sent = true;
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    await openForm();

    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    expect(await screen.findByText("Выберите вид документа.")).toBeVisible();
    expect(screen.getByText("Выберите, как получено письмо.")).toBeVisible();
    expect(screen.getByText("Укажите корреспондента.")).toBeVisible();
    expect(screen.getByText("Укажите тему.")).toBeVisible();
    expect(screen.getByText("Приложите файл письма и дождитесь загрузки.")).toBeVisible();
    expect(sent).toBe(false);
  });

  it("требование ГНК: «срочно» и кабинет налогоплательщика подставляются; ВХ-номер и переход во «Входящие»", async () => {
    let body = null as LetterRegisterIn | null;
    server.use(
      http.post("*/eds/letters", async ({ request }) => {
        body = (await request.clone().json()) as LetterRegisterIn;
        return undefined;
      }),
    );
    await openForm();

    await chooseOption(screen.getByLabelText("Вид документа"), "Требование или уведомление ГНК");
    expect(screen.getByRole("checkbox", { name: "Срочно" })).toBeChecked();
    expect(selectedLabel(screen.getByLabelText("Способ получения"))).toBe(
      "Кабинет налогоплательщика my.soliq",
    );
    type("Корреспондент", "ГНИ Мирабадского района");
    type("Исходящий номер отправителя", "04-12/9999");
    type("Тема", "Требование о пояснениях");
    // P8b: адресат — выбор сотрудника; пусто — директор по умолчанию (назначает EDS)
    expect(screen.getByText("Директор (по умолчанию)")).toBeVisible();
    await attach();

    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    expect(await screen.findByText("Зарегистрировано: ВХ-109/26")).toBeVisible();
    await waitFor(() => {
      expect(body).not.toBeNull();
    });
    expect(body).toMatchObject({
      kind: "tax_notice",
      receipt_method: "taxpayer_cabinet",
      sender_name: "ГНИ Мирабадского района",
      sender_ref_number: "04-12/9999",
      subject: "Требование о пояснениях",
      urgent: true,
      summary: null,
    });
    expect(body?.file_ids).toHaveLength(1);
    expect(await screen.findByRole("heading", { level: 1, name: "Входящие" })).toBeVisible();
  });

  it("похожее (тот же корреспондент и исх. № без даты): ссылка на ВХ, регистрация не запрещена", async () => {
    await openForm();

    type("Корреспондент", "гни  демо-района");
    type("Исходящий номер отправителя", "№ 04-12/3456");

    expect(await screen.findByText("Похожие письма", {}, { timeout: 3000 })).toBeVisible();
    expect(screen.getByRole("link", { name: "ВХ-108/26" })).toHaveAttribute(
      "href",
      "/eds/inbox/%D0%92%D0%A5-108%2F26",
    );
    expect(screen.getByText(/тот же исх\. №/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Зарегистрировать" })).toBeEnabled();
  });

  it("то же письмо (409): блок с ВХ, «Это другое письмо» требует причину и уходит с force", async () => {
    const bodies: LetterRegisterIn[] = [];
    server.use(
      http.post("*/eds/letters", async ({ request }) => {
        const body = (await request.clone().json()) as LetterRegisterIn;
        bodies.push(body);
        if (body.force) return undefined;
        return HttpResponse.json(
          {
            code: "CONFLICT",
            message: "Это письмо уже зарегистрировано: ВХ-108/26.",
            source: "eds",
            details: {
              reason: "duplicate_letter",
              duplicate: {
                id: "11111111-1111-4111-8111-111111111111",
                number: "ВХ-108/26",
                subject: "Требование о представлении пояснений",
                received_at: "2026-10-29",
                registered_at: "2026-10-29T09:00:00Z",
                status: "in_execution",
                match: "exact",
                path: "/eds/inbox/%D0%92%D0%A5-108%2F26",
              },
            },
          },
          { status: 409 },
        );
      }),
    );
    await openForm();
    await chooseOption(screen.getByLabelText("Вид документа"), "Требование или уведомление ГНК");
    type("Корреспондент", "ГНИ Другого района");
    type("Исходящий номер отправителя", "77-01/1");
    type("Тема", "Требование о пояснениях");
    await attach();

    fireEvent.click(screen.getByRole("button", { name: /Зарегистрировать$/ }));

    expect(await screen.findByText("Похоже, это письмо уже зарегистрировано")).toBeVisible();
    expect(screen.getByText(/Это письмо уже зарегистрировано: ВХ-108\/26/)).toBeVisible();
    expect(screen.getByText("На исполнении")).toBeVisible();
    // Правка ключевого поля — найденный по 409 ВХ снимается (проверка заново); вернули — снова он.
    type("Исходящий номер отправителя", "77-01/2");
    expect(screen.queryByText("Похоже, это письмо уже зарегистрировано")).toBeNull();
    type("Исходящий номер отправителя", "77-01/1");
    expect(screen.getByText("Похоже, это письмо уже зарегистрировано")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Это другое письмо — зарегистрировать" }));
    fireEvent.click(screen.getByRole("button", { name: /Зарегистрировать$/ }));
    expect(await screen.findByText("Укажите причину — она попадёт в журнал")).toBeVisible();
    expect(bodies).toHaveLength(1);

    type("Почему это другое письмо", "Повторное письмо с исправлениями");
    fireEvent.click(screen.getByRole("button", { name: /Зарегистрировать$/ }));

    expect(await screen.findByText(/Зарегистрировано: ВХ-/)).toBeVisible();
    expect(bodies[1]).toMatchObject({
      force: true,
      force_reason: "Повторное письмо с исправлениями",
    });
  });

  it("связанный документ с несуществующим номером — ошибка у поля, введённое остаётся", async () => {
    await openForm();
    await chooseOption(screen.getByLabelText("Вид документа"), "Письмо банка");
    await chooseOption(screen.getByLabelText("Способ получения"), "Почта");
    type("Корреспондент", "АКБ «Демо-Банк»");
    type("Тема", "Изменение тарифов");
    type("Связанный документ", "ВХ-999/26");
    await attach();

    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    expect(await screen.findAllByText(/Документа с таким номером нет/)).not.toHaveLength(0);
    expect(screen.getByLabelText("Тема")).toHaveValue("Изменение тарифов");
  });
});

describe("Карточка ВХ: делопроизводитель готовит проект, директор накладывает резолюцию (P8, P8b)", () => {
  it("делопроизводитель видит реквизиты делопроизводства и «Только просмотр»; вместо резолюции — проект", async () => {
    signIn("registrar@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution");

    expect(await screen.findByRole("heading", { level: 1, name: /ВХ-108\/26/ })).toBeVisible();
    expect(await screen.findByText("Требование или уведомление ГНК")).toBeVisible();
    expect(screen.getByText("Кабинет налогоплательщика my.soliq")).toBeVisible();
    expect(screen.getByText("Только просмотр")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Утвердить резолюцию/ })).toBeNull();
    // P8b: письмо делопроизводства — делопроизводитель готовит проект, резолюцию не накладывает
    expect(
      await screen.findByRole("button", { name: "Сохранить проект" }, { timeout: 3000 }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Утвердить проект" })).toBeNull();
  });

  it("директор видит то же письмо с резолюцией трёх типов (путь делопроизводства)", async () => {
    signIn("director@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution");

    expect(await screen.findByRole("heading", { level: 1, name: /ВХ-108\/26/ })).toBeVisible();
    expect(screen.queryByText("Только просмотр")).toBeNull();
    const form = await screen.findByRole(
      "form",
      { name: "Резолюция директора" },
      { timeout: 3000 },
    );
    expect(within(form).getByRole("radio", { name: /К исполнению/ })).toBeChecked();
    expect(within(form).getByRole("radio", { name: /Подготовить ответ/ })).not.toBeChecked();
    expect(within(form).getByRole("radio", { name: /Для сведения/ })).not.toBeChecked();
    expect(within(form).getByRole("button", { name: "Наложить резолюцию" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Утвердить резолюцию/ })).toBeNull();
  });
});

describe("EDS · справочники в форме регистрации (EDS-REG)", () => {
  it("способы получения и виды — из справочника: скрытого нет, добавленный администратором есть", async () => {
    const state = readDictionaries();
    writeDictionaries({
      ...state,
      "letter-kinds": state["letter-kinds"].map((item) =>
        item.code === "bank" ? { ...item, active: false } : item,
      ),
      "receipt-methods": [
        ...state["receipt-methods"].map((item) =>
          item.code === "courier" ? { ...item, active: false } : item,
        ),
        {
          code: "fax",
          name: { ru: "Факс", uz: "", en: "" },
          attrs: {},
          active: true,
          position: 60,
        },
      ],
    });
    await openForm();

    const titles = () =>
      Array.from(
        document.querySelectorAll<HTMLElement>(
          ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
        ),
      ).map((item) => item.getAttribute("title") ?? item.textContent);
    fireEvent.mouseDown(screen.getByLabelText("Способ получения"));
    await waitFor(() => {
      expect(titles()).toContain("Факс");
    });
    expect(titles()).not.toContain("Курьер");
    fireEvent.keyDown(screen.getByLabelText("Способ получения"), { key: "Escape" });

    fireEvent.mouseDown(screen.getByLabelText("Вид документа"));
    await waitFor(() => {
      expect(titles()).toContain("Письмо поставщика");
    });
    expect(titles()).not.toContain("Письмо банка");
  });
});

describe("registerModel", () => {
  it("обязательные поля и дата поступления не позже сегодня", () => {
    const empty = emptyRegister("2026-11-01");
    expect(Object.keys(validateRegister(empty, "2026-11-01")).sort()).toEqual(
      ["file_ids", "kind", "receipt_method", "sender_name", "subject"].sort(),
    );
    const future = { ...empty, receivedAt: "2026-11-02", senderInn: "12" };
    expect(validateRegister(future, "2026-11-01")).toMatchObject({
      received_at: true,
      sender_inn: true,
    });
  });

  it("тело запроса: пустые строки — null, номер заявки из подписи выбора, файлы без повторов", () => {
    const values = {
      ...emptyRegister("2026-11-01"),
      kind: "bank",
      receiptMethod: "post",
      senderName: "  Банк ",
      subject: " Тарифы ",
      deal: { erp_deal_id: 5, label: "ЗВ-2026-104 · Стрелочные приводы · ООО «Демо-Рейл»" },
      attachments: [
        { key: "a", name: "a.pdf", size: 1, status: "done" as const, id: "f1" },
        { key: "b", name: "b.pdf", size: 1, status: "done" as const, id: "f1" },
        { key: "c", name: "c.pdf", size: 1, status: "error" as const },
      ],
    };
    expect(toRegisterBody(values)).toMatchObject({
      kind: "bank",
      receipt_method: "post",
      sender_name: "Банк",
      subject: "Тарифы",
      summary: null,
      sender_ref_number: null,
      related_number: null,
      erp_deal_id: 5,
      deal_number: "ЗВ-2026-104",
      file_ids: ["f1"],
    });
  });
});
