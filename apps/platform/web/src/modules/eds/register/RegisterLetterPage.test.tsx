import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import type { LetterRegisterIn } from "../../../shared/api/generated/model";
import { chooseOption, selectedLabel } from "../../../test/fields";
import { setupLetterTests } from "../../../test/lettersKit";
import { renderAt, signIn } from "../../../test/edsKit";
import { server } from "../../../test/server";
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
    let body: LetterRegisterIn | null = null;
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
    expect(screen.getByLabelText("Адресат")).toHaveValue("Директор");
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
    expect(await screen.findByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
  });

  it("дубль (тот же корреспондент и исх. №): предупреждение со ссылкой на ВХ, регистрация не запрещена", async () => {
    await openForm();

    type("Корреспондент", "гни  демо-района");
    type("Исходящий номер отправителя", "04-12/3456");

    const warning = await screen.findByText(
      /Возможно, это письмо уже зарегистрировано/,
      {},
      {
        timeout: 3000,
      },
    );
    expect(warning).toBeVisible();
    expect(screen.getByRole("link", { name: "ВХ-108/26" })).toHaveAttribute(
      "href",
      "/eds/inbox/%D0%92%D0%A5-108%2F26",
    );
    expect(screen.getByRole("button", { name: "Зарегистрировать" })).toBeEnabled();
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

describe("Карточка ВХ: делопроизводитель без резолюции, директор с резолюцией (P8)", () => {
  it("делопроизводитель видит реквизиты делопроизводства и «Только просмотр», кнопки резолюции нет", async () => {
    signIn("registrar@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution");

    expect(await screen.findByRole("heading", { level: 1, name: /ВХ-108\/26/ })).toBeVisible();
    expect(await screen.findByText("Требование или уведомление ГНК")).toBeVisible();
    expect(screen.getByText("Кабинет налогоплательщика my.soliq")).toBeVisible();
    expect(screen.getByText("Только просмотр")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Наложить резолюцию" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Утвердить резолюцию/ })).toBeNull();
    expect(await screen.findByText("Письмо ждёт резолюции директора")).toBeVisible();
  });

  it("директор видит то же письмо с формой резолюции", async () => {
    signIn("director@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution");

    expect(await screen.findByRole("heading", { level: 1, name: /ВХ-108\/26/ })).toBeVisible();
    expect(screen.queryByText("Только просмотр")).toBeNull();
    expect(
      await screen.findByRole("button", { name: /Утвердить резолюцию/ }, { timeout: 3000 }),
    ).toBeVisible();
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
      receiptMethod: "post" as const,
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
