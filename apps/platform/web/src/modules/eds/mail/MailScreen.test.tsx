import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { MOCK_IMAP_OFF_KEY, resetInboundMailMock } from "../../../mocks/inboundMail";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";

setupLetterTests();
beforeEach(() => {
  resetInboundMailMock();
});

const REGISTRAR = "registrar@demo.example";

async function listOf(name: string) {
  return screen.findByRole("list", { name });
}

describe("Документы · Входящая почта: список (W18A-P2, W18A-P2-3)", () => {
  it("делопроизводитель видит шесть вкладок со счётчиками и новые письма", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail");
    const list = await listOf("Письма, ждущие разбора");
    expect(within(list).getAllByRole("listitem")).toHaveLength(4);
    for (const name of [
      "Новые · 4",
      "Мои в работе · 0",
      "Все в работе · 2",
      "Разобранные · 4",
      "Подозрительные · 1",
      "Все · 10",
    ]) {
      expect(screen.getByRole("tab", { name })).toBeVisible();
    }
    expect(
      within(list).getByRole("link", { name: "Открыть письмо «Акт сверки за октябрь»" }),
    ).toHaveAttribute("href", "/eds/mail/17");
    expect(within(list).getByText("Счёт или документ поставщика")).toBeVisible();
    expect(within(list).getByText("Вложений: 1")).toBeVisible();
  });

  it("непрочитанное письмо — жирным, прочитанное — обычным; словом «Не прочитано» для скринридера", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail");
    const list = await listOf("Письма, ждущие разбора");
    const unread = within(list).getByRole("link", {
      name: "Открыть письмо «Акт сверки за октябрь»",
    });
    const read = within(list).getByRole("link", {
      name: "Открыть письмо «Запрос КП на стрелочные переводы»",
    });
    expect(unread).toHaveClass("pf-mail-unread");
    expect(read).not.toHaveClass("pf-mail-unread");
    expect(within(list).getAllByText("Не прочитано").length).toBeGreaterThan(0);
  });

  it("ответ в цепочке — «Новое · ответ в цепочке», прежний исполнитель — справкой, писем — три", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail");
    const list = await listOf("Письма, ждущие разбора");
    const row = within(list)
      .getByRole("link", { name: "Открыть письмо «Re: Счёт на оплату № 118»" })
      .closest("li");
    if (!row) throw new Error("нет строки");
    expect(within(row).getByText("Новое · ответ в цепочке")).toBeVisible();
    expect(within(row).getByText("Вёл: Иванов Демо")).toBeVisible();
    expect(within(row).getByText("Писем: 2")).toBeVisible();
  });

  it("«Все в работе»: кто ведёт и с какого времени, метка «адресовано лично» из настроек", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail?tab=in_work");
    const list = await listOf("Письма в работе");
    const held = within(list)
      .getByRole("link", { name: "Открыть письмо «Счёт на смазку для стрелок»" })
      .closest("li");
    if (!held) throw new Error("нет строки");
    expect(within(held).getByText(/В работе у Иванов Демо с \d{2}:\d{2}/)).toBeVisible();
    expect(within(list).getByText("Адресовано лично")).toBeVisible();
  });

  it("«Разобранные»: итог словами со ссылками на ВХ и лид, кто и когда; «Вернуть в Новые» у архива и ответа", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail?tab=done");
    const list = await listOf("Разобранные письма");
    expect(within(list).getByRole("link", { name: "Зарегистрировано: ВХ-42/26" })).toHaveAttribute(
      "href",
      "/eds/inbox/%D0%92%D0%A5-42%2F26",
    );
    expect(within(list).getByRole("link", { name: "Лид L-2075" })).toBeVisible();
    expect(within(list).getByText("В архив: Рассылка")).toBeVisible();
    expect(within(list).getByText("Ответ отправлен")).toBeVisible();
    expect(within(list).getAllByText(/Иванов Демо, /)).not.toHaveLength(0);
    expect(within(list).getAllByRole("button", { name: "Вернуть в Новые" })).toHaveLength(2);

    fireEvent.click(
      within(list).getAllByRole("button", { name: "Вернуть в Новые" })[0] as HTMLElement,
    );
    expect(await screen.findByText("Письмо вернулось в «Новые»")).toBeVisible();
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Новые · 5" })).toBeVisible();
    });
  });

  it("поиск по отправителю и теме: запрос уходит после паузы, ничего не найдено — словами", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail");
    await listOf("Письма, ждущие разбора");
    fireEvent.change(screen.getByRole("searchbox", { name: "Поиск по отправителю и теме" }), {
      target: { value: "акт сверки" },
    });
    await waitFor(() => {
      expect(
        within(screen.getByRole("list", { name: "Письма, ждущие разбора" })).getAllByRole(
          "listitem",
        ),
      ).toHaveLength(1);
    });
    expect(
      screen.getByRole("link", { name: "Открыть письмо «Акт сверки за октябрь»" }),
    ).toBeVisible();
    fireEvent.change(screen.getByRole("searchbox", { name: "Поиск по отправителю и теме" }), {
      target: { value: "zzzz" },
    });
    expect(await screen.findByText("Ничего не найдено")).toBeVisible();
  });

  it("массово «В архив»: причина обязательна, в итоге названы пропущенные", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail?tab=all");
    const list = await listOf("Все письма");
    fireEvent.click(
      within(list).getByRole("checkbox", { name: "Выбрать письмо «Акт сверки за октябрь»" }),
    );
    fireEvent.click(
      within(list).getByRole("checkbox", { name: "Выбрать письмо «Счёт на смазку для стрелок»" }),
    );
    fireEvent.click(
      within(list).getByRole("checkbox", { name: "Выбрать письмо «Уведомление о сверке»" }),
    );
    expect(screen.getByText("Выбрано: 3")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "В архив" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("group", { name: "Что произойдёт" })).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Отправить в архив" });
    expect(confirm).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Рассылка" }));
    expect(within(dialog).getByLabelText("Причина")).toHaveValue("Рассылка");
    fireEvent.click(confirm);
    expect(
      await screen.findByText("В архив: 1. Пропущено: 2 — в работе у Иванов Демо; уже разобрано."),
    ).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByText("Выбрано: 3")).toBeNull();
    });
  });

  it("без настроенного приёма — понятная подсказка, где подключить", async () => {
    window.localStorage.setItem(MOCK_IMAP_OFF_KEY, "1");
    signIn(REGISTRAR);
    renderAt("/eds/mail");
    expect(await screen.findByRole("heading", { name: "Почта не подключена" })).toBeVisible();
    expect(screen.getByText(/Настройки · Подключения · Почта/)).toBeVisible();
  });

  it("менеджеру без первой линии раздел не открыт; свои письма — по «Моя почта»", async () => {
    signIn("universal@demo.example");
    renderAt("/eds/mail");
    expect(await screen.findByText(/не открыт|нет доступа|Нет доступа/i)).toBeVisible();
    expect(screen.queryByRole("list", { name: "Письма, ждущие разбора" })).toBeNull();
  });
});

describe("Своя почта сотрудника без первой линии (W18A-P2-3)", () => {
  it("видит только письмо, адресованное ему лично: три вкладки, без поиска очереди и массовых действий", async () => {
    signIn("universal@demo.example");
    renderAt("/eds/my-mail");
    const list = await listOf("Мои письма в работе");
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(
      within(list).getByRole("link", {
        name: "Открыть письмо «Вопрос по гарантии на стрелочный привод»",
      }),
    ).toHaveAttribute("href", "/eds/my-mail/23");
    expect(screen.getByRole("tab", { name: "Мои в работе · 1" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Все мои · 1" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: /Подозрительные/ })).toBeNull();
    expect(within(list).queryByRole("checkbox")).toBeNull();
    expect(within(list).getByText("Адресовано лично")).toBeVisible();
  });
});

describe("Входящая почта: «Подозрительные» и «из истории» (W18A-P2-2)", () => {
  it("письмо из «Спама» — во вкладке «Подозрительные», не в очереди; «Не спам» возвращает его в «Новые»", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail");
    const queue = await listOf("Письма, ждущие разбора");
    expect(within(queue).queryByText(/тендере на поставку шпал/)).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Подозрительные · 1" }));
    const spam = await listOf("Подозрительные письма");
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
    expect(await screen.findByText("Письмо в «Новых»")).toBeVisible();
    expect(await screen.findByText("Подозрительных писем нет")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /^Новые/ }));
    const back = await listOf("Письма, ждущие разбора");
    await waitFor(() => {
      expect(within(back).getAllByRole("listitem")).toHaveLength(5);
    });
  });

  it("«Убрать» — в архив, письмо уходит из «Подозрительных»", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/20");
    fireEvent.click(await screen.findByRole("button", { name: "Убрать" }));
    expect(await screen.findByText("Письмо убрано в архив")).toBeVisible();
    expect(await screen.findByText("Подозрительных писем нет")).toBeVisible();
  });

  it("фильтр «Из истории»: пусто, пока администратор не загрузил письма за период", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail?show=history");
    expect(await screen.findByText("Писем из истории нет")).toBeVisible();
    expect(screen.getByRole("radio", { name: "Из истории · 0" })).toBeChecked();
  });
});
