import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { panelEl, renderAt, setupPaymentTests, signIn } from "../../../test/paymentsKit";

setupPaymentTests();

const OVER = "/eds/payments?show=overdue";

async function openInvoice(
  number: string,
  user = "accountant@demo.example",
  path = "/eds/payments",
) {
  signIn(user);
  const view = renderAt(path);
  fireEvent.click(
    await screen.findByRole("link", { name: `Показать счёт ${number} в боковом окне` }),
  );
  const panel = await panelEl();
  const form = await within(panel).findByRole("form", { name: "Подтверждение оплаты" });
  return { ...view, panel, form };
}

describe("Счета и оплаты: список", () => {
  it("бухгалтер: вкладки с числами, таблица «Ждут оплаты» со статусами словами", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments");

    expect(await screen.findByRole("heading", { level: 1, name: "Счета и оплаты" })).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Вкладки счетов и оплат" });
    expect(await within(nav).findByRole("link", { name: /^Ждут оплаты\s*2$/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: /^К выставлению\s*1$/ })).toBeVisible();
    expect(
      within(nav).getByRole("link", { name: /^Платёжки на подтверждение\s*1$/ }),
    ).toBeVisible();
    expect(within(nav).getByRole("link", { name: /^Просрочены\s*1$/ })).toBeVisible();
    expect(within(nav).getByRole("link", { name: /^Служебки к оплате\s*1$/ })).toBeVisible();

    const table = await screen.findByRole("table", { name: "Счета" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(1 + 2);
    const first = within(table).getByRole("row", { name: /СЧ-2026\/142/ });
    expect(within(first).getByText("ПР-2026-104")).toBeVisible();
    expect(within(first).getByText("ООО «Демо-Рейл»")).toBeVisible();
    expect(within(first).getByText("Выставлен")).toBeVisible();
    const partial = within(table).getByRole("row", { name: /СЧ-2026\/147/ });
    expect(within(partial).getByText("Частично оплачен")).toBeVisible();
    expect(within(partial).getByText(/остаток 30\s000\s000/)).toBeVisible();
  });

  it("«Просрочены» говорит, на сколько дней, и не хранит статус: просрочка видна словом", async () => {
    signIn("accountant@demo.example");
    renderAt(OVER);

    const row = await screen.findByRole("row", { name: /СЧ-2026\/144/ });
    expect(within(row).getByText("Просрочен")).toBeVisible();
    expect(within(row).getByText("просрочен на 8 дн.")).toBeVisible();
  });

  it("«Платёжки на подтверждение»: статус «Платёжка получена» и действие «Проверить платёжку»", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=proofs");

    const row = await screen.findByRole("row", { name: /СЧ-2026\/145/ });
    expect(within(row).getByText("Платёжка получена")).toBeVisible();
    expect(
      within(row).getByRole("link", { name: "Проверить платёжку: СЧ-2026/145" }),
    ).toHaveTextContent(/^Проверить$/);
  });

  it("поиск по номеру; пустой результат — словами и с действием", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=all");

    const search = await screen.findByRole("textbox", {
      name: "Поиск по номеру счёта или клиенту",
    });
    fireEvent.change(search, { target: { value: "ничего-такого" } });
    fireEvent.keyDown(search, { key: "Enter", code: "Enter", charCode: 13 });

    expect(await screen.findByRole("heading", { name: "Ничего не найдено" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Сбросить поиск" }));
    expect(await screen.findByRole("table", { name: "Счета" })).toBeVisible();
  });

  it("пустая вкладка: слова и действие (К выставлению без счетов)", async () => {
    server.use(
      http.get("*/eds/payments", () =>
        HttpResponse.json({
          tab: "to_issue",
          count: 0,
          counts: { to_issue: 0, awaiting: 0, proofs: 0, overdue: 0 },
          memos_to_pay: 0,
          items: [],
          sources: { erp: "ok", eds: "ok" },
        }),
      ),
    );
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=to_issue");

    expect(await screen.findByRole("heading", { name: "Счетов к выставлению нет" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Ждут оплаты" })).toBeVisible();
  });

  it("менеджер (только чтение): счета ERP ему не показываются словами, служебки к оплате доступны", async () => {
    signIn("manager@demo.example");
    renderAt("/eds/payments");

    expect(
      await screen.findByRole("heading", { name: "Счета клиентов вам не показываются" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: /Служебки к оплате/ }));
    const table = await screen.findByRole("table", { name: "Служебки к оплате" });
    expect(within(table).getByText("СЗ-2026/015")).toBeVisible();
    expect(within(table).getByText("Приложен")).toBeVisible();
  });

  it("снабженец: раздела нет, «Нет доступа»", async () => {
    signIn("supply@demo.example");
    renderAt("/eds/payments");

    expect(await screen.findByRole("heading", { name: "Нет доступа" })).toBeVisible();
  });
});

describe("Подтвердить оплату", () => {
  it("по умолчанию сумма = остатку; полная оплата закрывает счёт и убирает его из «Ждут оплаты»", async () => {
    const { form, panel } = await openInvoice("СЧ-2026/142");

    const amount = within(form).getByLabelText(/Сумма по выписке/);
    expect(amount).toHaveValue("112000000.00");
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toHaveTextContent(
      "Счёт СЧ-2026/142 станет «Оплачен»",
    );
    fireEvent.click(within(form).getByRole("button", { name: "Подтвердить оплату" }));

    expect(await screen.findByText(/Оплата подтверждена: 112\s000\s000/)).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("row", { name: /СЧ-2026\/142/ })).toBeNull();
    });
    expect(within(panel).queryByRole("form", { name: "Подтверждение оплаты" })).toBeNull();
  });

  it("частичная оплата: кнопка меняет слова, остаток виден; счёт остаётся «Частично оплачен»", async () => {
    const { form } = await openInvoice("СЧ-2026/142");
    const amount = within(form).getByLabelText(/Сумма по выписке/);

    fireEvent.change(amount, { target: { value: "40 000 000" } });

    expect(
      within(form).getByRole("button", { name: "Подтвердить частичную оплату" }),
    ).toBeEnabled();
    const consequence = within(form).getByRole("group", { name: "Что произойдёт" });
    expect(consequence).toHaveTextContent("станет «Частично оплачен»");
    expect(consequence).toHaveTextContent(/остаток 72\s000\s000/);

    fireEvent.click(within(form).getByRole("button", { name: "Подтвердить частичную оплату" }));
    expect(await screen.findByText(/Частичная оплата подтверждена/)).toBeVisible();
    const row = await screen.findByRole("row", { name: /СЧ-2026\/142/ });
    expect(within(row).getByText("Частично оплачен")).toBeVisible();
    expect(within(row).getByText(/остаток 72\s000\s000/)).toBeVisible();
  });

  it("«Частичная оплата» очищает сумму и ставит курсор в поле; пока сумма не введена — кнопка неактивна с подписью", async () => {
    const { form } = await openInvoice("СЧ-2026/142");

    fireEvent.click(within(form).getByRole("button", { name: "Частичная оплата" }));

    const amount = within(form).getByLabelText(/Сумма по выписке/);
    expect(amount).toHaveValue("");
    expect(amount).toHaveFocus();
    const submit = within(form).getByRole("button", { name: "Подтвердить оплату" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAccessibleDescription(/Введите сумму больше нуля/);
  });

  it("сумма больше остатка: ответ ERP словами, введённое остаётся, ничего не записано", async () => {
    const { form } = await openInvoice("СЧ-2026/142");
    const amount = within(form).getByLabelText(/Сумма по выписке/);

    fireEvent.change(amount, { target: { value: "112000000.01" } });
    fireEvent.click(within(form).getByRole("button", { name: "Подтвердить оплату" }));

    expect(
      await within(form).findByText(/Не сохранено: сумма больше остатка по счёту \(112\s000\s000/),
    ).toBeVisible();
    expect(amount).toHaveValue("112000000.01");
  });

  it("платёжка клиента: выбирается в форме, подтверждается и получает статус «Оплата подтверждена»", async () => {
    const { form, panel } = await openInvoice(
      "СЧ-2026/145",
      "accountant@demo.example",
      "/eds/payments?show=proofs",
    );

    const proof = within(form).getByRole("radio", { name: "платёжка-0127.pdf" });
    expect(proof).toBeChecked();
    expect(within(panel).getByText("Кабинет клиента", { exact: false })).toBeVisible();
    fireEvent.click(within(form).getByRole("button", { name: "Подтвердить оплату" }));

    expect(await screen.findByText(/Оплата подтверждена: 28/)).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("row", { name: /СЧ-2026\/145/ })).toBeNull();
    });
  });

  it("повторное нажатие после ответа не создаёт второй платёж: тот же ключ — прежний ответ", async () => {
    const keys: (string | null)[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.method === "POST" && request.url.endsWith("/confirm")) {
        keys.push(request.headers.get("idempotency-key"));
      }
    });
    const { form } = await openInvoice("СЧ-2026/142");
    const submit = within(form).getByRole("button", { name: "Подтвердить оплату" });

    fireEvent.click(submit);
    fireEvent.click(submit);

    await screen.findAllByText(/Оплата подтверждена: 112/);
    const sent = keys.filter((key): key is string => key !== null);
    expect(sent.length).toBeGreaterThanOrEqual(1);
    expect(new Set(sent).size).toBe(1);
    server.events.removeAllListeners();
  });
});

describe("Платёжки клиента и запрос платёжки", () => {
  it("«Запросить платёжку»: шаблон сообщения с номером, суммой и сроком; отметка попадает в журнал", async () => {
    const { panel } = await openInvoice("СЧ-2026/142");

    fireEvent.click(within(panel).getByRole("button", { name: "Запросить платёжку" }));

    const text = within(panel).getByLabelText<HTMLTextAreaElement>("Текст сообщения");
    expect(text.value).toContain("СЧ-2026/142");
    expect(text.value).toContain("Срок оплаты — 07.11.2026");
    expect(
      within(panel).getByText(/Автоматической отправки клиенту в бот и почту пока нет/),
    ).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Отметить: платёжку запросили" }));
    expect(await screen.findByText("Запрос платёжки отмечен в журнале счёта")).toBeVisible();
    expect(await within(panel).findByText(/Платёжку запросили/)).toBeVisible();
  });

  it("«Приложить платёжку»: без файла — подсказка, с файлом — платёжка в списке и счёт на вкладке «Платёжки»", async () => {
    const { panel } = await openInvoice("СЧ-2026/142");

    fireEvent.click(within(panel).getByRole("button", { name: "Приложить платёжку" }));
    const form = within(panel).getByRole("form", { name: "Платёжка клиента" });
    fireEvent.click(within(form).getByRole("button", { name: "Приложить" }));
    expect(await within(form).findByText("Выберите файл платёжки.")).toBeVisible();

    const file = new File(["%PDF-1.4"], "pp-142.pdf", { type: "application/pdf" });
    fireEvent.change(within(form).getByLabelText("Файл платёжки"), { target: { files: [file] } });
    fireEvent.click(within(form).getByRole("button", { name: "Приложить" }));

    expect(await screen.findByText("Платёжка приложена")).toBeVisible();
    expect(
      await within(panel).findByRole("link", { name: "Скачать платёжку pp-142.pdf" }),
    ).toBeVisible();
  });
});

describe("Служебки к оплате", () => {
  it("«Оплачено»: дата, сумма и платёжка; служебка уходит из «К оплате» и попадает в оплаченные", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=memos");

    const table = await screen.findByRole("table", { name: "Служебки к оплате" });
    const row = within(table).getByRole("row", { name: /СЗ-2026\/015/ });
    expect(within(row).getByText("Передана бухгалтеру")).toBeVisible();
    fireEvent.click(
      within(row).getByRole("link", { name: "Показать служебку СЗ-2026/015 в боковом окне" }),
    );
    const panel = await panelEl();
    const form = await within(panel).findByRole("form", { name: "Оплата служебной записки" });
    expect(within(form).getByLabelText(/Сумма оплаты/)).toHaveValue("4200000.00");
    expect(within(panel).getByRole("link", { name: "Скачать счёт-аренда.pdf" })).toBeVisible();

    const file = new File(["%PDF-1.4"], "pp-015.pdf", { type: "application/pdf" });
    fireEvent.change(within(form).getByLabelText(/Платёжка/), { target: { files: [file] } });
    fireEvent.click(within(form).getByRole("button", { name: "Оплачено" }));

    expect(await screen.findByText("Служебка СЗ-2026/015 оплачена")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("row", { name: /СЗ-2026\/015/ })).toBeNull();
    });
    fireEvent.click(screen.getByRole("radio", { name: "Оплаченные" }));
    const paid = await screen.findByRole("row", { name: /СЗ-2026\/015/ });
    expect(within(paid).getByText(/Оплачена/)).toBeVisible();
  });

  it("сумма больше согласованной: кнопка неактивна, причина названа", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments/60000000-0000-4000-8000-000000000015");

    const panel = await panelEl();
    const form = await within(panel).findByRole("form", { name: "Оплата служебной записки" });
    fireEvent.change(within(form).getByLabelText(/Сумма оплаты/), {
      target: { value: "4200000.01" },
    });

    const submit = within(form).getByRole("button", { name: "Оплачено" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAccessibleDescription(/Введите сумму больше нуля/);
  });

  it("«Вернуть автору»: причина обязательна, после возврата служебки в списке к оплате нет", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=memos");
    fireEvent.click(
      await screen.findByRole("link", { name: "Показать служебку СЗ-2026/015 в боковом окне" }),
    );
    const panel = await panelEl();
    const form = await within(panel).findByRole("form", { name: "Оплата служебной записки" });

    fireEvent.click(within(form).getByRole("button", { name: "Вернуть автору" }));
    const send = within(form).getByRole("button", { name: "Вернуть служебку" });
    expect(send).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Причина возврата"), {
      target: { value: "Нет реквизитов" },
    });
    fireEvent.click(send);

    expect(await screen.findByText("Служебка возвращена автору")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("row", { name: /СЗ-2026\/015/ })).toBeNull();
    });
  });

  it("менеджер: служебка к оплате открывается только для просмотра, формы «Оплачено» нет", async () => {
    signIn("manager@demo.example");
    renderAt("/eds/payments?show=memos");
    fireEvent.click(
      await screen.findByRole("link", { name: "Показать служебку СЗ-2026/015 в боковом окне" }),
    );
    const panel = await panelEl();

    expect(await within(panel).findByRole("heading", { name: "Только просмотр" })).toBeVisible();
    expect(within(panel).queryByRole("form", { name: "Оплата служебной записки" })).toBeNull();
  });
});

describe("Карточка счёта", () => {
  it("состав, оплаты, платёжки и журнал; адрес по номеру переводит на карточку", async () => {
    signIn("accountant@demo.example");
    renderAt(`/eds/payments/${encodeURIComponent("СЧ-2026/147")}`);

    expect(await screen.findByRole("heading", { level: 1, name: "СЧ-2026/147" })).toBeVisible();
    expect(screen.getByRole("table", { name: "Позиции счёта" })).toBeVisible();
    const payments = screen.getByRole("table", { name: "Оплаты по счёту" });
    expect(within(payments).getByText("BANK-147")).toBeVisible();
    expect(screen.getByRole("list", { name: "Журнал счёта" })).toHaveTextContent(
      "Оплата подтверждена",
    );
  });

  it("ссылка из очереди с номером и ?panel=open&tab=payment: карточка по id, боковое окно остаётся", async () => {
    signIn("accountant@demo.example");
    const { router } = renderAt(
      `/eds/payments/${encodeURIComponent("СЧ-2026/142")}?panel=open&tab=payment`,
    );

    expect(await screen.findByRole("heading", { level: 1, name: "СЧ-2026/142" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/eds/payments/142");
    expect(router.state.location.search).toBe("?panel=open&tab=payment");
    const panel = await panelEl();
    expect(await within(panel).findByRole("form", { name: "Подтверждение оплаты" })).toBeVisible();
  });

  it("счёта нет: «Счёт не найден» и ссылка к списку", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments/999");

    expect(await screen.findByRole("heading", { name: "Счёт не найден" })).toBeVisible();
    expect(screen.getByRole("link", { name: "К списку счетов" })).toBeVisible();
  });
});
