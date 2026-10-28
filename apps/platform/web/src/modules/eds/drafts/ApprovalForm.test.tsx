import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { findQuote } from "../../../mocks/fixtures/approvals";
import { server } from "../../../test/server";
import { panelEl, renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";

setupApprovalTests();

const QUOTE = (n: number) => `/eds/drafts/${encodeURIComponent(`КП-2026/${String(n)}`)}`;
const APPROVE = "Одобрить КП → отправить клиенту";

async function openForm(n = 115, user = "director@demo.example") {
  signIn(user);
  const view = renderAt(QUOTE(n));
  const panel = await panelEl();
  const form = await within(panel).findByRole("form", { name: "Одобрение КП" });
  return { ...view, panel, form };
}

function draftKeys(): string[] {
  return Object.keys(window.sessionStorage).filter((k) => k.startsWith("rt-pf-quote-draft-v1"));
}

describe("Одобрение КП: форма", () => {
  it("чек-лист с датой и автором, каналы по контакту, «Что произойдёт», главная кнопка активна", async () => {
    const { form } = await openForm();

    const checklist = within(form).getByRole("list", { name: "Чек-лист одобрения" });
    const rows = within(checklist).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("Виза снабженца");
    expect(rows[0]).toHaveTextContent("Демо Снабженцев");
    expect(rows[1]).toHaveTextContent("Демо Инженеров");
    expect(within(form).getByRole("checkbox", { name: "Telegram-бот" })).toBeChecked();
    expect(within(form).getByRole("checkbox", { name: "Кабинет" })).toBeChecked();
    expect(within(form).getByRole("checkbox", { name: "Почта" })).toBeChecked();
    const consequence = within(form).getByRole("group", { name: "Что произойдёт" });
    expect(within(consequence).getAllByRole("listitem")).toHaveLength(3);
    expect(consequence).toHaveTextContent("Telegram-бот, Кабинет, Почта");
    expect(within(form).getByRole("button", { name: APPROVE })).toBeEnabled();
  });

  it("красные блокирующие строки: кнопка неактивна, подпись называет каждый не зелёный пункт", async () => {
    const { form } = await openForm(116);
    const approve = within(form).getByRole("button", { name: APPROVE });

    expect(approve).toBeDisabled();
    expect(approve).toHaveAccessibleDescription(
      "Одобрить нельзя: нет визы гл. инженера, маржа ниже порога резолюции.",
    );
    expect(within(form).getByRole("checkbox", { name: "Кабинет" })).toBeDisabled();
    expect(within(form).getByText("Недоступен: у компании клиента нет кабинета.")).toBeVisible();
  });

  it("срок клиента просрочен — предупреждение, не блок; почта недоступна с подписью", async () => {
    const { form } = await openForm(117);

    expect(within(form).getByRole("button", { name: APPROVE })).toBeEnabled();
    expect(within(form).getByText(/просрочен, это предупреждение/)).toBeVisible();
    expect(
      within(form).getByText(/в журнале появится отметка «одобрено с опозданием»/),
    ).toBeVisible();
    expect(within(form).getByRole("checkbox", { name: "Почта" })).toBeDisabled();
    expect(within(form).getByText("Недоступна: у контакта не указан e-mail.")).toBeVisible();
    expect(
      within(within(form).getByRole("group", { name: "Что произойдёт" })).getByText(
        /\(Telegram-бот, Кабинет\)/,
      ),
    ).toBeVisible();
  });

  it("«Вернуть на доработку»: комментарий обязателен, кнопка неактивна с подписью", async () => {
    const { form } = await openForm();
    const back = within(form).getByRole("button", { name: "Вернуть на доработку" });

    expect(back).toBeDisabled();
    expect(back).toHaveAccessibleDescription(/Кнопка неактивна, пока нет комментария/);
    fireEvent.change(within(form).getByLabelText("Комментарий"), { target: { value: "   " } });
    expect(back).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Пересчитать доставку" },
    });
    expect(back).toBeEnabled();
  });

  it("в EDS уходят отмеченные каналы; снятый канал в запрос не попадает", async () => {
    let body: unknown;
    server.use(
      http.post("*/eds/quotes/:id/decision", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ code: "x", message: "x", source: "bff" }, { status: 500 });
      }),
    );
    const { form } = await openForm();
    fireEvent.click(within(form).getByRole("checkbox", { name: "Почта" }));

    fireEvent.click(within(form).getByRole("button", { name: APPROVE }));

    await waitFor(() => {
      expect(body).toEqual({ decision: "approve", channels: ["telegram", "cabinet"] });
    });
  });

  it("EDS недоступен: «Не сохранено: …», комментарий и выбранные каналы остаются, черновик сохранён", async () => {
    server.use(
      http.post("*/eds/quotes/:id/decision", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "Сервис недоступен.", source: "eds" },
          { status: 503 },
        ),
      ),
    );
    const { form } = await openForm();
    fireEvent.click(within(form).getByRole("checkbox", { name: "Почта" }));
    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Подтверждаю по звонку" },
    });

    fireEvent.click(within(form).getByRole("button", { name: APPROVE }));

    expect(
      await within(form).findByText(
        "Не сохранено: сервис документов не отвечает, введённое осталось в форме",
      ),
    ).toBeVisible();
    expect(within(form).getByLabelText("Комментарий")).toHaveValue("Подтверждаю по звонку");
    expect(within(form).getByRole("checkbox", { name: "Почта" })).not.toBeChecked();
    expect(draftKeys()).toHaveLength(1);

    // закрыли вкладку и открыли КП снова — введённое восстановлено
    cleanup();
    const again = await openForm();
    expect(again.form).toHaveTextContent("Комментарий восстановлен из черновика.");
    expect(within(again.form).getByLabelText("Комментарий")).toHaveValue("Подтверждаю по звонку");
    expect(within(again.form).getByRole("checkbox", { name: "Почта" })).not.toBeChecked();
  });

  it("409 «чек-лист не выполнен»: коды красных строк словами, введённое остаётся", async () => {
    server.use(
      http.post("*/eds/quotes/:id/decision", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "Чек-лист не выполнен.",
            source: "eds",
            details: { reason: "checklist_not_green", failed: ["visa_services", "margin"] },
          },
          { status: 409 },
        ),
      ),
    );
    const { form } = await openForm();
    fireEvent.change(within(form).getByLabelText("Комментарий"), { target: { value: "Срочно" } });

    fireEvent.click(within(form).getByRole("button", { name: APPROVE }));

    expect(
      await within(form).findByText(
        "Не сохранено: чек-лист не выполнен (нет визы гл. инженера, маржа ниже порога резолюции), карточка обновлена",
      ),
    ).toBeVisible();
    expect(within(form).getByLabelText("Комментарий")).toHaveValue("Срочно");
  });

  it("409 «КП уже решено»: сообщение словами, карточка обновилась, формы больше нет, черновик стёрт", async () => {
    const { panel } = await openForm();
    // другой директор вернул КП, пока форма открыта
    await fetch("/api/v1/eds/quotes/40000000-0000-4000-8000-000000000115/decision", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision: "return", comment: "дубль" }),
    });
    const form = within(panel).getByRole("form", { name: "Одобрение КП" });
    fireEvent.change(within(form).getByLabelText("Комментарий"), { target: { value: "ок" } });

    fireEvent.click(within(form).getByRole("button", { name: APPROVE }));

    expect(
      await screen.findAllByText(
        "Не сохранено: КП уже решено другим директором или заменено новой версией, карточка обновлена",
      ),
    ).not.toHaveLength(0);
    expect(
      await within(panel).findByRole("heading", { name: "КП возвращено на доработку" }),
    ).toBeVisible();
    expect(within(panel).queryByRole("form", { name: "Одобрение КП" })).toBeNull();
    expect(draftKeys()).toHaveLength(0);
  });

  it("менеджер: формы решения нет, внутренних полей нет", async () => {
    signIn("manager@demo.example");
    renderAt(QUOTE(115));
    const panel = await panelEl();

    expect(
      await within(panel).findByRole("heading", { name: "КП ждёт решения директора" }),
    ).toBeVisible();
    expect(within(panel).queryByRole("form")).toBeNull();
    expect(await screen.findByText("Только просмотр")).toBeVisible();
    expect(screen.queryByText("Внутренние данные")).toBeNull();
    expect(screen.queryByText("Себестоимость")).toBeNull();
    expect(screen.queryByText(/17\.6/)).toBeNull();
  });

  it("карточка директора: внутренний блок с маржой и подписью; итоги и строки КП", async () => {
    await openForm();

    const internal = await screen.findByRole("region", { name: "Внутренние данные" });
    expect(within(internal).getByText("Себестоимость")).toBeVisible();
    expect(within(internal).getByText(/17\.6 %/)).toBeVisible();
    expect(within(internal).getByText("Клиент получит PDF без этих полей.")).toBeVisible();
    const lines = screen.getByRole("table", { name: "Состав КП" });
    expect(within(lines).getAllByRole("row")).toHaveLength(1 + 2);
    expect(screen.getByText("Итого с НДС")).toBeVisible();
  });

  it("«Что произойдёт» не обещает отправку: «Готово к отправке», клиенту отправит менеджер заявки", async () => {
    const { form } = await openForm();
    const consequence = within(form).getByRole("group", { name: "Что произойдёт" });

    expect(consequence).toHaveTextContent("станет «Готово к отправке»");
    expect(consequence).toHaveTextContent("его отправит менеджер заявки");
    expect(consequence).not.toHaveTextContent("КП · Отправлено");
  });

  it("без каналов главная кнопка — «Одобрить КП → в Исходящие»", async () => {
    const { form } = await openForm();
    for (const name of ["Telegram-бот", "Кабинет", "Почта"]) {
      fireEvent.click(within(form).getByRole("checkbox", { name }));
    }

    expect(within(form).getByRole("button", { name: "Одобрить КП → в Исходящие" })).toBeEnabled();
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toHaveTextContent(
      "Каналы не выбраны",
    );
  });

  it("состав КП из ERP не получен: «Одобрить» неактивна с подписью, виден итог снимка", async () => {
    const { form } = await openForm(118);
    const approve = within(form).getByRole("button", { name: APPROVE });

    expect(approve).toBeDisabled();
    expect(approve).toHaveAccessibleDescription("Нет данных КП из ERP — обновите карточку.");
    expect(await screen.findByText("Итог по снимку КП")).toBeVisible();
    expect(screen.getByText(/Состав КП не получен из ERP/)).toBeVisible();
    // вернуть на доработку можно и без данных ERP
    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Обновите расчёт" },
    });
    expect(within(form).getByRole("button", { name: "Вернуть на доработку" })).toBeEnabled();
  });

  it("итог ERP расходится со снимком EDS — предупреждение у итогов", async () => {
    server.use(
      http.get("*/eds/quotes/:ref", () =>
        HttpResponse.json({
          ...findQuote("КП-2026/115"),
          totals_mismatch: true,
          totals: { ...findQuote("КП-2026/115")?.totals, total: "126000000.00" },
        }),
      ),
    );
    signIn("director@demo.example");
    renderAt(QUOTE(115));

    expect(await screen.findByText(/расходится с итогом снимка КП/)).toBeVisible();
  });

  it("список адресует КП по id маршрута, а не по номеру", async () => {
    signIn("director@demo.example");
    const { router } = renderAt("/eds/drafts");
    const link = await screen.findByRole("link", { name: "Открыть карточку КП КП-2026/115" });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("40000000-0000-4000-8000-000000000115"),
    );

    fireEvent.click(screen.getByRole("link", { name: "Показать КП КП-2026/115 в боковом окне" }));
    expect(router.state.location.search).toContain("quote=40000000-0000-4000-8000-000000000115");
  });

  it("ссылка из «Моей очереди» (КП-2026/118, panel=open) открывает карточку и «Одобрение»", async () => {
    signIn("director@demo.example");
    renderAt(`/eds/drafts/${encodeURIComponent("КП-2026/118")}?panel=open&tab=approve`);

    expect(await screen.findByRole("heading", { level: 1, name: "КП-2026/118" })).toBeVisible();
    const panel = await panelEl();
    expect(await within(panel).findByRole("form", { name: "Одобрение КП" })).toBeVisible();
  });
});
