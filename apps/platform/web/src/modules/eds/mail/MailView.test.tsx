import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { resetInboundMailMock } from "../../../mocks/inboundMail";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";
import { server } from "../../../test/server";

setupLetterTests();
beforeEach(() => {
  resetInboundMailMock();
});

const REGISTRAR = "registrar@demo.example";
const heading = (name: string) => screen.findByRole("heading", { level: 1, name });

describe("Карточка письма: подсказка и действия (W18A-P2)", () => {
  it("подсказка — только по кнопке и ничего не делает сама; «Создать лид» одним подтверждением", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/18");
    expect(await heading("Запрос КП на стрелочные переводы")).toBeVisible();
    expect(screen.queryByText("Покупатель")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Подсказать" }));
    expect(await screen.findByText("Покупатель")).toBeVisible();
    expect(screen.getByText("Предлагает: Создать лид")).toBeVisible();
    expect(screen.getByText("Новое")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Создать лид" }));
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    const [, confirm] = screen.getAllByRole("button", { name: "Создать лид" });
    if (!confirm) throw new Error("нет кнопки подтверждения");
    fireEvent.click(confirm);
    expect(await screen.findByText(/Лид L-2068 создан/)).toBeVisible();
    const list = await screen.findByRole("list", { name: "Письма, ждущие разбора" });
    await waitFor(() => {
      expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    });
  });

  it("«В архив» — только с причиной", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/19");
    fireEvent.click(await screen.findByRole("button", { name: "В архив" }));
    const confirm = screen.getByRole("button", { name: "Отправить в архив" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Причина"), { target: { value: "реклама" } });
    fireEvent.click(confirm);
    expect(await screen.findByText("Письмо в архиве")).toBeVisible();
  });

  it("«Зарегистрировать входящее» открывает форму, заполненную из письма, с вложением и адресатами из копии", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/17");
    const register = await screen.findByRole("link", { name: "Зарегистрировать входящее" });
    expect(register).toHaveAttribute("href", "/eds/register?mail=17");
    fireEvent.click(register);
    expect(
      await screen.findByText("Из письма: «Акт сверки за октябрь» от ООО «Демо-Поставка»"),
    ).toBeVisible();
    expect(screen.getByLabelText(/Тема/)).toHaveValue("Акт сверки за октябрь");
    expect(await screen.findByText("акт-сверки-октябрь.pdf")).toBeVisible();
  });
});

describe("«В работе»: взять, перехватить, вернуть (W18A-P2-3)", () => {
  it("«Взять в работу» — письмо у вас, в «Моих в работе» одно, главное действие — «Вернуть в Новые»", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/18");
    fireEvent.click(await screen.findByRole("button", { name: "Взять в работу" }));
    expect(await screen.findByText("Письмо в работе у вас")).toBeVisible();
    expect(await screen.findByText("В работе", { selector: ".ant-tag *, .ant-tag" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Взять в работу" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Вернуть в Новые" }));
    expect(await screen.findByText("Письмо вернулось в «Новые»")).toBeVisible();
    expect(await screen.findByRole("button", { name: "Взять в работу" })).toBeVisible();
  });

  it("письмо ведёт коллега: действий нет, только «Забрать себе» с подтверждением «Что произойдёт»", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/21");
    expect(
      await screen.findByText(/Письмо уже в работе у Иванов Демо с \d{2}:\d{2}/),
    ).toBeVisible();
    expect(screen.queryByRole("link", { name: "Зарегистрировать входящее" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Создать лид" })).toBeNull();
    expect(screen.queryByLabelText("Текст ответа")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Забрать себе" }));
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    const confirm = screen.getAllByRole("button", { name: "Забрать себе" })[0];
    if (!confirm) throw new Error("нет кнопки подтверждения");
    fireEvent.click(confirm);
    expect(await screen.findByText("Письмо в работе у вас")).toBeVisible();
    expect(await screen.findByRole("link", { name: "Зарегистрировать входящее" })).toBeVisible();
  });

  it("действие, на которое опередил коллега (409): сообщение словами и «Забрать себе»", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/18");
    const card = await screen.findByRole("button", { name: "Создать лид" });
    // Пока человек думал, коллега взял письмо: сервер отвечает 409, карточка обновляется.
    server.use(
      http.post("*/inbound-mail/18/lead", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "Письмо уже в работе у Иванов Демо с 10:42.",
            source: "crm",
            details: {
              reason: "mail_in_work_by_other",
              assignee_name: "Иванов Демо",
              assigned_at: "2026-11-03T05:42:00Z",
            },
          },
          { status: 409 },
        ),
      ),
    );
    fireEvent.click(card);
    const [, confirm] = screen.getAllByRole("button", { name: "Создать лид" });
    if (!confirm) throw new Error("нет кнопки подтверждения");
    fireEvent.click(confirm);
    expect(
      await screen.findByText(/Не получилось: Письмо уже в работе у Иванов Демо с 10:42/),
    ).toBeVisible();
  });
});

describe("Переписка, адресаты, журнал (W18A-P2-3)", () => {
  it("цепочка: входящие и наш ответ по времени, вложение ответа качается по id письма; журнал без текстов", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/22");
    expect(await heading("Re: Счёт на оплату № 118")).toBeVisible();
    expect(
      screen.getByText("Новое · ответ в цепочке", { selector: ".ant-tag *, .ant-tag" }),
    ).toBeVisible();
    const thread = screen.getByRole("list", { name: "Переписка" });
    const entries = Array.from(thread.children);
    expect(entries).toHaveLength(3);
    expect(within(entries[0] as HTMLElement).getByText(/Подскажите реквизиты/)).toBeVisible();
    expect(
      within(entries[1] as HTMLElement).getByText(/Ответ отправлен: Иванов Демо/),
    ).toBeVisible();
    expect(within(entries[2] as HTMLElement).getByText(/Платёж отправили/)).toBeVisible();
    expect(
      within(entries[2] as HTMLElement).getByRole("link", { name: "Скачать платёжка-118.pdf" }),
    ).toHaveAttribute("href", "/api/v1/inbound-mail/122/attachments/0");
    expect(screen.getByText("Журнал")).toBeVisible();
    expect(screen.getByText(/Иванов Демо · взял в работу/)).toBeVisible();
    expect(screen.getByText(/клиент ответил в цепочке/)).toBeVisible();
  });

  it("адресаты: сотрудник по адресу и общий ящик названы, копия отдельно; «адресовано лично» с пометкой", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/23");
    expect(await heading("Вопрос по гарантии на стрелочный привод")).toBeVisible();
    expect(screen.getByText("Демо Широков (сотрудник), shirokov@railtech.example")).toBeVisible();
    expect(screen.getByText("info@company.example (общий ящик)")).toBeVisible();
    expect(screen.getAllByText("Адресовано лично").length).toBeGreaterThan(0);
  });

  it("открытие карточки отмечает письмо прочитанным (счётчик «не прочитано» падает)", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/17");
    await heading("Акт сверки за октябрь");
    fireEvent.click(await screen.findByRole("link", { name: "Входящая почта" }));
    const list = await screen.findByRole("list", { name: "Письма, ждущие разбора" });
    const link = within(list).getByRole("link", { name: "Открыть письмо «Акт сверки за октябрь»" });
    await waitFor(() => {
      expect(link).not.toHaveClass("pf-mail-unread");
    });
  });
});

describe("Ответ (W18A-P2-3)", () => {
  it("«Ответить» — «Разобрано: ответ отправлен»; «Ответить всем» показывает, кому уйдёт копия; «Ждём ответа» оставляет в работе", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/17");
    const text = await screen.findByLabelText("Текст ответа");
    expect(
      screen.getByText(/Копия уйдёт: buh.copy@company.example, sidorov@railtech.example/),
    ).toBeVisible();
    fireEvent.change(text, { target: { value: "Подпишем и вернём." } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Ждём ответа/ }));
    fireEvent.click(screen.getByRole("button", { name: "Ответить всем" }));
    expect(await screen.findByText("Ответ отправлен, письмо остаётся в работе")).toBeVisible();
    expect(await screen.findByText("В работе", { selector: ".ant-tag *, .ant-tag" })).toBeVisible();

    fireEvent.change(await screen.findByLabelText("Текст ответа"), {
      target: { value: "Готово, отправили скан." },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Ждём ответа/ }));
    fireEvent.click(screen.getByRole("button", { name: "Отправить ответ" }));
    expect(
      await screen.findByText("Разобрано", { selector: ".ant-tag *, .ant-tag" }),
    ).toBeVisible();
    expect(screen.getByText("Ответ отправлен")).toBeVisible();
  });

  it("у письма без копии «Ответить всем» недоступно", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/18");
    fireEvent.change(await screen.findByLabelText("Текст ответа"), {
      target: { value: "Добрый день" },
    });
    expect(screen.getByRole("button", { name: "Ответить всем" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Отправить ответ" })).toBeEnabled();
  });
});

describe("Сотрудник без первой линии со своим письмом (W18A-P2-3)", () => {
  it("видит переписку и отвечает; действий первой линии нет; может вернуть делопроизводителю", async () => {
    signIn("universal@demo.example");
    renderAt("/eds/my-mail/23");
    expect(await heading("Вопрос по гарантии на стрелочный привод")).toBeVisible();
    expect(screen.getByLabelText("Текст ответа")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Зарегистрировать входящее" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Создать лид" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Взять в работу" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Вернуть делопроизводителю" }));
    expect(await screen.findByText("Письмо вернулось в «Новые»")).toBeVisible();
  });

  it("чужое письмо — «не найдено», а не содержимое", async () => {
    signIn("universal@demo.example");
    renderAt("/eds/my-mail/17");
    expect(await screen.findByRole("heading", { name: /не найден/i })).toBeVisible();
  });
});
