import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { MOCK_IMAP_OFF_KEY, resetInboundMailMock } from "../../../mocks/inboundMail";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";
import { arrivedAt, prefillFromMail } from "./mailModel";

setupLetterTests();
beforeEach(() => {
  resetInboundMailMock();
});

describe("Документы · Входящая почта (W18A-P2)", () => {
  it("делопроизводитель видит очередь: отправитель, тема, подсказка, вложения", async () => {
    signIn("registrar@demo.example");
    renderAt("/eds/mail");
    const list = await screen.findByRole("list", { name: "Письма, ждущие разбора" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(
      within(list).getByRole("link", { name: "Открыть письмо «Акт сверки за октябрь»" }),
    ).toHaveAttribute("href", "/eds/mail/17");
    expect(within(list).getByText("Счёт или документ поставщика")).toBeVisible();
    expect(within(list).getByText("Вложений: 1")).toBeVisible();
  });

  it("без настроенного приёма — понятная подсказка, где подключить", async () => {
    window.localStorage.setItem(MOCK_IMAP_OFF_KEY, "1");
    signIn("registrar@demo.example");
    renderAt("/eds/mail");
    expect(await screen.findByRole("heading", { name: "Почта не подключена" })).toBeVisible();
    expect(screen.getByText(/Настройки · Подключения · Почта/)).toBeVisible();
  });

  it("подсказка — только по кнопке и ничего не делает сама; «Создать лид» одним подтверждением", async () => {
    signIn("registrar@demo.example");
    renderAt("/eds/mail/18");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Запрос КП на стрелочные переводы" }),
    ).toBeVisible();
    expect(screen.queryByText("Покупатель")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Подсказать" }));
    expect(await screen.findByText("Покупатель")).toBeVisible();
    expect(screen.getByText("Предлагает: Создать лид")).toBeVisible();
    // Подсказка ничего не сделала: письмо всё ещё ждёт разбора.
    expect(screen.getByText("Ждёт разбора")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Создать лид" }));
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    const [, confirm] = screen.getAllByRole("button", { name: "Создать лид" });
    if (!confirm) throw new Error("нет кнопки подтверждения");
    fireEvent.click(confirm);
    expect(await screen.findByText(/Лид L-2068 создан/)).toBeVisible();
    const list = await screen.findByRole("list", { name: "Письма, ждущие разбора" });
    await waitFor(() => {
      expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    });
  });

  it("«В архив» — только с причиной", async () => {
    signIn("registrar@demo.example");
    renderAt("/eds/mail/19");
    fireEvent.click(await screen.findByRole("button", { name: "В архив" }));
    const confirm = screen.getByRole("button", { name: "Отправить в архив" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Причина"), { target: { value: "реклама" } });
    fireEvent.click(confirm);
    expect(await screen.findByText("Письмо в архиве")).toBeVisible();
  });

  it("«Зарегистрировать входящее» открывает форму P8, заполненную из письма, с вложением", async () => {
    signIn("registrar@demo.example");
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

  it("менеджеру без первой линии раздел не открыт", async () => {
    signIn("universal@demo.example");
    renderAt("/eds/mail");
    expect(await screen.findByText(/не открыт|нет доступа|Нет доступа/i)).toBeVisible();
    expect(screen.queryByRole("list", { name: "Письма, ждущие разбора" })).toBeNull();
  });
});

describe("Входящая почта: «Подозрительные» и «из истории» (W18A-P2-2)", () => {
  it("письмо из «Спама» — во вкладке «Подозрительные», не в очереди; «Не спам» возвращает его в очередь", async () => {
    signIn("registrar@demo.example");
    renderAt("/eds/mail");
    const queue = await screen.findByRole("list", { name: "Письма, ждущие разбора" });
    expect(within(queue).queryByText(/тендере на поставку шпал/)).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Подозрительные · 1" }));
    const spam = await screen.findByRole("list", { name: "Подозрительные письма" });
    fireEvent.click(
      await within(spam).findByRole("link", {
        name: "Открыть письмо «Приглашение к участию в тендере на поставку шпал»",
      }),
    );
    expect(
      await screen.findByText("Подозрительное", { selector: ".ant-tag *, .ant-tag" }),
    ).toBeVisible();
    expect(screen.getByText(/отметьте его в почте «Не спам»/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Зарегистрировать входящее" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Не спам → в очередь" }));
    expect(await screen.findByText("Письмо в очереди «Ждут разбора»")).toBeVisible();
    expect(await screen.findByText("Подозрительных писем нет")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /Ждут разбора/ }));
    const back = await screen.findByRole("list", { name: "Письма, ждущие разбора" });
    await waitFor(() => {
      expect(within(back).getAllByRole("listitem")).toHaveLength(4);
    });
  });

  it("«Убрать» — в архив, письмо уходит из «Подозрительных»", async () => {
    signIn("registrar@demo.example");
    renderAt("/eds/mail/20");
    fireEvent.click(await screen.findByRole("button", { name: "Убрать" }));
    expect(await screen.findByText("Письмо убрано в архив")).toBeVisible();
    expect(await screen.findByText("Подозрительных писем нет")).toBeVisible();
  });

  it("фильтр «Из истории»: пусто, пока администратор не загрузил письма за период", async () => {
    signIn("registrar@demo.example");
    renderAt("/eds/mail?show=history");
    expect(await screen.findByText("Писем из истории нет")).toBeVisible();
    expect(screen.getByRole("radio", { name: "Из истории · 0" })).toBeChecked();
  });
});

describe("arrivedAt", () => {
  it("у письма «из истории» — дата письма, у обычного — когда пришло в ящик", () => {
    const mail = { sent_at: "2026-10-01T05:00:00Z", received_at: "2026-11-03T05:00:00Z" };
    expect(arrivedAt({ ...mail, from_history: true })).toBe("2026-10-01T05:00:00Z");
    expect(arrivedAt({ ...mail, from_history: false })).toBe("2026-11-03T05:00:00Z");
    expect(arrivedAt({ ...mail, sent_at: null, from_history: true })).toBe("2026-11-03T05:00:00Z");
  });
});

describe("prefillFromMail", () => {
  it("переносит корреспондента, дату, суть, вложения и источник; вид — только однозначный", () => {
    const values = prefillFromMail(
      {
        id: 5,
        status: "new",
        from_email: "a@b.example",
        from_name: "",
        subject: "Счёт",
        received_at: "2026-11-01T20:30:00Z",
        sent_at: null,
        preview: "",
        attachments_count: 0,
        assist: { status: "done", kind: "official", summary: "Письмо банка", action: "register" },
        client: null,
        lead: null,
        from_history: false,
        to: [],
        text: "Текст",
        attachments: [],
        skipped: [],
        too_large: false,
        inns: ["301234567"],
        letter_number: null,
        letter_ref: null,
        result_lead: null,
        archive_reason: null,
        handled_at: null,
        replies: [],
      },
      [],
    );
    expect(values).toMatchObject({
      kind: "",
      receiptMethod: "email",
      senderName: "a@b.example",
      senderInn: "301234567",
      receivedAt: "2026-11-02",
      summary: "Письмо банка",
      sourceMailId: 5,
      attachments: [],
    });
  });
});
