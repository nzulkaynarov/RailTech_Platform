import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { readMemos, writeMemos } from "../../../mocks/fixtures/approvals";
import { findInvoice } from "../../../mocks/fixtures/payments";
import { server } from "../../../test/server";
import { panelEl, renderAt, setupPaymentTests, signIn } from "../../../test/paymentsKit";
import { decisionEl, openSideTab } from "../../../test/panel";
import { confirmDialog } from "../../../test/confirmDialog";

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

    expect(await screen.findByRole("heading", { level: 1, name: "Финансы" })).toBeVisible();
    expect(await screen.findByRole("radio", { name: "Ждут оплаты · 2" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "К выставлению · 1" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Оплаты на подтверждение · 1" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Просрочены · 1" })).toBeInTheDocument();

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

  it("«Оплаты на подтверждение»: статус «Оплата на проверке» и действие «Проверить платёжное поручение»", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=proofs");

    const row = await screen.findByRole("row", { name: /СЧ-2026\/145/ });
    expect(within(row).getByText("Оплата на проверке")).toBeVisible();
    expect(
      within(row).getByRole("link", { name: "Проверить платёжное поручение: СЧ-2026/145" }),
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

  it("менеджер и директор (только чтение): счета видны, карточка без формы; записки к оплате доступны", async () => {
    signIn("director@demo.example");
    renderAt("/eds/payments");

    // В строке — «Открыть», а не «Подтвердить»: оплату подтверждает бухгалтер.
    expect(
      await screen.findByRole("link", { name: "Открыть карточку счёта: СЧ-2026/142" }),
    ).toBeVisible();
    expect(screen.queryByRole("link", { name: /^Подтвердить оплату:/ })).toBeNull();
    fireEvent.click(
      await screen.findByRole("link", { name: "Показать счёт СЧ-2026/142 в боковом окне" }),
    );
    const panel = await panelEl();
    expect(await within(panel).findByRole("heading", { name: "Только просмотр" })).toBeVisible();
    expect(within(panel).queryByRole("form", { name: "Подтверждение оплаты" })).toBeNull();
  });

  it("роль без права ERP на счета (выдана вручную): счета ERP не показываются словами, записки доступны", async () => {
    server.use(
      http.get("*/eds/payments", () =>
        HttpResponse.json(
          {
            code: "FORBIDDEN",
            message: "Раздел или действие не положены вашей роли.",
            source: "erp",
            details: { backend_status: 403, backend_code: "ROLE_NOT_PERMITTED" },
          },
          { status: 403 },
        ),
      ),
    );
    signIn("manager@demo.example");
    renderAt("/eds/payments");

    expect(
      await screen.findByRole("heading", { name: "Счета клиентов вам не показываются" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: "Заявки на оплату" }));
    const table = await screen.findByRole("table", { name: "Заявки на оплату" });
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
    expect(amount).toHaveValue("112\u00a0000\u00a0000");
    fireEvent.click(within(form).getByRole("button", { name: "Подтвердить оплату" }));
    await confirmDialog();

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

    fireEvent.click(within(form).getByRole("button", { name: "Подтвердить частичную оплату" }));

    await confirmDialog();
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
    await confirmDialog();

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
    expect(within(panel).getByText(/Комментарий клиента: Оплатили из двух счетов/)).toBeVisible();
    fireEvent.click(within(form).getByRole("button", { name: "Подтвердить оплату" }));
    await confirmDialog();

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
    await confirmDialog();

    await screen.findAllByText(/Оплата подтверждена: 112/);
    const sent = keys.filter((key): key is string => key !== null);
    expect(sent.length).toBeGreaterThanOrEqual(1);
    expect(new Set(sent).size).toBe(1);
    server.events.removeAllListeners();
  });
});

describe("Платёжные поручения и запрос платёжки", () => {
  it("«Запросить платёжное поручение»: шаблон сообщения с номером, суммой и сроком; отметка попадает в журнал", async () => {
    const { panel } = await openInvoice("СЧ-2026/142");

    fireEvent.click(within(panel).getByRole("button", { name: "Запросить платёжное поручение" }));

    const text = within(panel).getByLabelText<HTMLTextAreaElement>("Текст сообщения");
    expect(text.value).toContain("СЧ-2026/142");
    expect(text.value).toContain("Срок оплаты — 07.11.2026");
    expect(within(panel).getByText(/Скопируйте текст, отправьте его клиенту/)).toBeVisible();
    fireEvent.click(
      within(panel).getByRole("button", { name: "Отметить: платёжное поручение запросили" }),
    );
    expect(
      await screen.findByText("Запрос платёжного поручения отмечен в журнале счёта"),
    ).toBeVisible();
    expect(await within(panel).findByText(/Платёжное поручение запросили/)).toBeVisible();
  });

  it("«Приложить платёжное поручение»: без файла — подсказка, с файлом — платёжка в списке и счёт на вкладке «Платёжки»", async () => {
    const { panel } = await openInvoice("СЧ-2026/142");

    fireEvent.click(within(panel).getByRole("button", { name: "Приложить платёжное поручение" }));
    const form = within(panel).getByRole("form", { name: "Платёжное поручение клиента" });
    fireEvent.click(within(form).getByRole("button", { name: "Приложить" }));
    expect(await within(form).findByText("Выберите файл платёжного поручения.")).toBeVisible();

    const file = new File(["%PDF-1.4"], "pp-142.pdf", { type: "application/pdf" });
    fireEvent.change(within(form).getByLabelText("Файл платёжного поручения"), {
      target: { files: [file] },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Приложить" }));

    expect(await screen.findByText("Платёжное поручение приложено")).toBeVisible();
    expect(
      await within(panel).findByRole("link", { name: "Скачать платёжное поручение pp-142.pdf" }),
    ).toBeVisible();
  });
});

describe("Записки к оплате", () => {
  it("«Оплачено»: дата, сумма и платёжка; записка уходит из «К оплате» и попадает в оплаченные", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=memos");

    const table = await screen.findByRole("table", { name: "Заявки на оплату" });
    const row = within(table).getByRole("row", { name: /СЗ-2026\/015/ });
    expect(within(row).getByText("Передана на оплату")).toBeVisible();
    fireEvent.click(
      within(row).getByRole("link", { name: "Показать записку СЗ-2026/015 в боковом окне" }),
    );
    const panel = await panelEl();
    const form = await within(panel).findByRole("form", { name: "Оплата служебной записки" });
    expect(within(form).getByLabelText(/Сумма оплаты/)).toHaveValue("4\u00a0200\u00a0000");
    expect(within(panel).getByRole("link", { name: "Скачать счёт-аренда.pdf" })).toBeVisible();

    const file = new File(["%PDF-1.4"], "pp-015.pdf", { type: "application/pdf" });
    fireEvent.change(within(form).getByLabelText(/Платёжное поручение/), {
      target: { files: [file] },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Оплачено" }));
    await confirmDialog();

    expect(await screen.findByText("Записка СЗ-2026/015 оплачена")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("row", { name: /СЗ-2026\/015/ })).toBeNull();
    });
    fireEvent.click(screen.getByRole("radio", { name: "Оплаченные" }));
    const paid = await screen.findByRole("row", { name: /СЗ-2026\/015/ });
    expect(within(paid).getByText(/Оплачена/)).toBeVisible();
  });

  it("без счёта: «не приложен»; с отметкой автора «счёт придёт позже» — «напомнить автору», а не «верните» (Б-9)", async () => {
    const id = "60000000-0000-4000-8000-000000000015";
    const bare = (extra: object) => {
      writeMemos(readMemos().map((m) => (m.id === id ? { ...m, files: [], ...extra } : m)));
    };
    bare({});
    signIn("accountant@demo.example");
    renderAt(`/eds/payments/${id}`);
    await decisionEl();
    expect(await screen.findByText(/Счёт партнёра не приложен/)).toBeVisible();
    cleanup();

    bare({ invoice_later: true });
    signIn("accountant@demo.example");
    renderAt(`/eds/payments/${id}`);
    await decisionEl();
    expect(await screen.findByText("Счёт придёт позже — напомнить автору")).toBeVisible();
    expect(screen.queryByText(/Верните записку автору/)).toBeNull();
  });

  it("сумма больше согласованной: кнопка неактивна, причина названа", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments/60000000-0000-4000-8000-000000000015");

    const panel = await decisionEl();
    const form = await within(panel).findByRole("form", { name: "Оплата служебной записки" });
    fireEvent.change(within(form).getByLabelText(/Сумма оплаты/), {
      target: { value: "4200000.01" },
    });

    const submit = within(form).getByRole("button", { name: "Оплачено" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAccessibleDescription(/Введите сумму больше нуля/);
  });

  it("«Вернуть автору»: причина обязательна, после возврата записки в списке к оплате нет", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=memos");
    fireEvent.click(
      await screen.findByRole("link", { name: "Показать записку СЗ-2026/015 в боковом окне" }),
    );
    const panel = await panelEl();
    const form = await within(panel).findByRole("form", { name: "Оплата служебной записки" });

    fireEvent.click(within(form).getByRole("button", { name: "Вернуть автору" }));
    const send = within(form).getByRole("button", { name: "Вернуть записку" });
    expect(send).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Причина возврата"), {
      target: { value: "Нет реквизитов" },
    });
    fireEvent.click(send);

    expect(await screen.findByText("Записка возвращена автору")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("row", { name: /СЗ-2026\/015/ })).toBeNull();
    });
  });

  it("менеджер: записка к оплате открывается только для просмотра, формы «Оплачено» нет", async () => {
    signIn("manager@demo.example");
    renderAt("/eds/payments?show=memos");
    fireEvent.click(
      await screen.findByRole("link", { name: "Показать записку СЗ-2026/015 в боковом окне" }),
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
    // Журнал — одна «История» в боковом окне, в центре его нет (ЕД-7)
    expect(screen.queryByRole("heading", { name: "Журнал" })).toBeNull();
    const history = await openSideTab("История");
    expect(within(history).getByRole("list", { name: "Журнал счёта" })).toHaveTextContent(
      "Оплата подтверждена",
    );
  });

  it("каждое сведение один раз: номер и статус — в шапке, клиент и проект — в «Сведениях», платёжки — одним списком в центре", async () => {
    server.use(
      http.get("*/eds/payments/:id", () =>
        HttpResponse.json({
          ...findInvoice(142),
          proofs: [
            {
              id: 5,
              source: "EMAIL",
              status: "PENDING",
              original_name: "пп-142.pdf",
              claimed_amount: null,
              claimed_date: null,
              note: "",
              received_at: "2026-10-27T15:00:00Z",
              recorded_by: null,
              payment_id: null,
            },
          ],
        }),
      ),
    );
    signIn("accountant@demo.example");
    renderAt(`/eds/payments/${encodeURIComponent("СЧ-2026/142")}`);

    expect(await screen.findByRole("heading", { level: 1, name: "СЧ-2026/142" })).toBeVisible();
    // в рабочей области номер один раз (последняя крошка в шапке страницы называет тот же счёт)
    expect(within(screen.getByRole("main")).getAllByText("СЧ-2026/142")).toHaveLength(1);
    const facts = await openSideTab("Сведения");
    expect(within(facts).getAllByText("Клиент", { selector: "dt" })).toHaveLength(1);
    expect(screen.getAllByText("ООО «Демо-Рейл»")).toHaveLength(1);
    expect(within(facts).queryByText("Сумма", { selector: "dt" })).toBeNull();
    // форма подтверждения — в центре, а не вкладкой «Оплата»
    expect(
      within(await decisionEl()).getByRole("form", { name: "Подтверждение оплаты" }),
    ).toBeVisible();
    expect(within(await panelEl()).queryByRole("tab", { name: "Оплата" })).toBeNull();
    expect(screen.getAllByRole("list", { name: "Платёжные поручения" })).toHaveLength(1);
  });

  it("ссылка из очереди с номером и ?panel=open&tab=payment: карточка по id, боковое окно остаётся", async () => {
    signIn("accountant@demo.example");
    const { router } = renderAt(
      `/eds/payments/${encodeURIComponent("СЧ-2026/142")}?panel=open&tab=payment`,
    );

    expect(await screen.findByRole("heading", { level: 1, name: "СЧ-2026/142" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/eds/payments/142");
    // Старая вкладка «Оплата» — теперь блок в центре: ссылка ведёт к форме и снимает параметры окна
    const center = await decisionEl();
    expect(await within(center).findByRole("form", { name: "Подтверждение оплаты" })).toBeVisible();
    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
  });

  it("записка к оплате: тема один раз, журнал — «История», форма «Оплачено» — в центре, окно — «Сведения»", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments/60000000-0000-4000-8000-000000000015");

    const center = await decisionEl();
    expect(
      await within(center).findByRole("form", { name: "Оплата служебной записки" }),
    ).toBeVisible();
    expect(await screen.findByRole("heading", { level: 1, name: "СЗ-2026/015" })).toBeVisible();
    expect(screen.getAllByText("Оплата командировочных расходов")).toHaveLength(1);
    expect(screen.queryByRole("heading", { name: "Журнал" })).toBeNull();
    const side = await panelEl();
    const tabs = within(side)
      .getAllByRole("tab")
      .map((tab) => tab.textContent);
    expect(tabs).toEqual(["Сведения", "История"]);
  });

  it("счёта нет: «Счёт не найден» и ссылка к списку", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments/999");

    expect(await screen.findByRole("heading", { name: "Счёт не найден" })).toBeVisible();
    expect(screen.getByRole("link", { name: "К списку счетов" })).toBeVisible();
  });
});

describe("Платёжка у оплаченного счёта", () => {
  it("неподтверждённая платёжка по уже оплаченному счёту названа лишней, а не «Ждёт подтверждения»", async () => {
    server.use(
      http.get("*/eds/payments/:id", () => {
        const proof = {
          id: 5,
          source: "EMAIL",
          status: "PENDING",
          original_name: "повтор.pdf",
          claimed_amount: null,
          claimed_date: null,
          note: "",
          received_at: "2026-10-27T15:00:00Z",
          recorded_by: null,
          payment_id: null,
        };
        return HttpResponse.json({
          ...findInvoice(146),
          proofs: [proof],
          can_confirm: false,
          can_attach_proof: false,
          can_request_proof: false,
        });
      }),
    );
    signIn("accountant@demo.example");
    renderAt("/eds/payments/146");

    const lists = await screen.findAllByRole("list", { name: "Платёжные поручения" });
    expect(lists).toHaveLength(1);
    for (const list of lists) {
      expect(within(list).getByText("Лишняя: счёт уже оплачен")).toBeVisible();
      expect(within(list).queryByText("Ждёт подтверждения")).toBeNull();
    }
  });
});

describe("Счета и оплаты: порядок по шапке (Х-15б)", () => {
  const spy = () => {
    const asked: (string | null)[] = [];
    server.use(
      http.get("*/eds/payments", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("sort"));
        return undefined; // дальше отвечает общий мок, он тоже сортирует по белому списку
      }),
    );
    return asked;
  };
  const numbers = () =>
    within(screen.getByRole("table", { name: "Счета" }))
      .getAllByRole("row")
      .slice(1)
      .map((tr) => (tr as HTMLTableRowElement).cells.item(0)?.textContent.slice(0, 12));

  it("щелчок по «Сумме» и «Счёту» уходит серверу как sort, весь список меняет порядок, а не страница", async () => {
    const asked = spy();
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=all");
    await screen.findByRole("table", { name: "Счета" });
    expect(asked).toEqual([null]);
    const before = numbers();

    fireEvent.click(screen.getByRole("button", { name: "Счёт и проект" }));
    fireEvent.click(await screen.findByRole("button", { name: /Счёт и проект/ }));
    await waitFor(() => {
      expect(asked).toContain("-number");
    });
    await waitFor(() => {
      expect(numbers()).toEqual([...before].sort().reverse());
    });

    fireEvent.click(screen.getByRole("button", { name: "Сумма" }));
    await waitFor(() => {
      expect(asked).toContain("amount");
    });
  });

  it("порядок из адреса уходит серверу, чужое поле — нет", async () => {
    const asked = spy();
    signIn("accountant@demo.example");
    renderAt("/eds/payments?show=all&sort=-due");
    await screen.findByRole("table", { name: "Счета" });
    expect(asked).toEqual(["-due"]);

    cleanup();
    asked.length = 0;
    renderAt("/eds/payments?show=all&sort=deal__company__name");
    await screen.findByRole("table", { name: "Счета" });
    expect(asked).toEqual([null]);
  });
});

/** ЕД-3: компания строки — логотип по адресу BFF с версией, а без логотипа — буквы названия, та же ячейка везде. */
function expectCompanyPictures(scope: HTMLElement) {
  const logos = Array.from(scope.querySelectorAll<HTMLImageElement>("img"));
  expect(logos.length).toBeGreaterThan(0);
  for (const img of logos) {
    expect(img.getAttribute("src")).toMatch(
      /^\/api\/v1\/people\/counterparties\/\d+\/logo\?v=\w+$/,
    );
  }
  expect(
    scope.querySelectorAll('.pf-entity__pic--square[data-photo="false"]').length,
  ).toBeGreaterThan(0);
}

describe("Счета и оплаты: логотип клиента в строке (ЕД-3)", () => {
  it("логотип по адресу с версией или буквы названия — в каждой строке", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/payments?tab=all");
    expectCompanyPictures(await screen.findByRole("table", { name: "Счета" }));
  });
});
