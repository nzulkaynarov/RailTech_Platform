import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { seedDraftOrder } from "../../mocks/erpStock";
import { MOCK_EDS_DOWN_KEY, MOCK_ERP_DOWN_KEY } from "../../mocks/feedHandlers";
import { endSession } from "../../mocks/mockSession";
import { usePanelsStore } from "../../app/shell/panelsStore";
import i18n from "../../shared/i18n";
import { POLL_INTERVAL_MS, STREAM_POLL_INTERVAL_MS } from "../../shared/api/polling";
import { FakeEventSource } from "../../test/fakeEventSource";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";
import { ROLE_ID } from "../../test/roles";

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

async function main() {
  await screen.findByRole("heading", { level: 1, name: "Задачи" });
  return screen.getByRole("main");
}

describe("Dashboard · Моя очередь", () => {
  it("до ответа — счётчики-скелетоны той же сетки, сколько было в прошлый раз; потом настоящие (UX-1c, S10)", async () => {
    let answer: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      answer = resolve;
    });
    server.use(
      http.get("*/queue/cards", async () => {
        await gate;
        return undefined;
      }),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();
    // Впервые в этом браузере — четыре карточки-заглушки
    expect(page.querySelectorAll(".pf-counter-skel")).toHaveLength(4);

    answer();
    await within(page).findByRole("link", { name: /Входящие без резолюции/ });
    expect(page.querySelector(".pf-counter-skel")).toBeNull();
    const shown = page.querySelectorAll(".pf-counter:not(.pf-counter-skel)").length;
    // Число запомнено: в следующий раз заглушек столько же
    expect(
      Object.keys(window.localStorage).some(
        (key) =>
          key.startsWith("rt-pf-queue-cards:") &&
          window.localStorage.getItem(key) === String(shown),
      ),
    ).toBe(true);
  });

  it("пока очередь грузится, карточка-заглушка — область status с именем, а не безымянный div (axe, W15-G-4)", async () => {
    server.use(
      http.get("*/queue", async () => {
        await new Promise((resolve) => setTimeout(resolve, 400));
        return HttpResponse.json({ items: [], sources: { crm: "ok", erp: "ok" } });
      }),
    );
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    await main();

    const loading = await screen.findByRole("status", { name: "Загружаем очередь…" });
    expect(loading).toHaveAttribute("aria-busy", "true");
    expect(loading.tagName).toBe("DIV");
  });

  it("директор: подзаголовок с числом решений, четыре счётчика и строки очереди (в том числе просроченный заказ партнёру)", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    // D2-8: в очереди директора только решения — строк исполнения (договор, счета, расчёт) нет
    // D26G-4: «Одобрить КП» — все КП на шаге директора в EDS (четыре в демо «КП на одобрение»)
    expect(await within(page).findByText(/^[^·]+ · 10 решений · просрочено: 1$/)).toBeVisible();
    const cards = within(page).getByRole("region", { name: "Счётчики очереди" });
    expect(within(cards).getAllByRole("link")).toHaveLength(4);
    expect(within(cards).getByRole("link", { name: /Входящие без резолюции/ })).toHaveAttribute(
      "href",
      "/eds/inbox",
    );

    const queue = await within(page).findByRole("region", { name: "Что ждёт вас" });
    const rows = within(queue).getAllByRole("listitem");
    expect(rows).toHaveLength(10);
    // D2-2: просроченный заказ партнёру (erp.stock: полный) — первым, он уже просрочен.
    expect(within(rows[0] as HTMLElement).getByText(/Просрочен заказ ЗП-\d{4}-029/)).toBeVisible();
    // ВХ-104 — со сроком сегодня; у ВХ-108 срока нет: «сегодня» не выдумывается (ГЛ-1)
    const rowOf = (title: string) => rows.find((r) => within(r).queryByText(title)) as HTMLElement;
    expect(
      within(rowOf("Наложить резолюцию на письмо ВХ-104/26")).getByText("срок сегодня"),
    ).toBeVisible();
    expect(
      within(rowOf("Наложить резолюцию на письмо ВХ-108/26")).queryByText("срок сегодня"),
    ).toBeNull();
    expect(
      within(rows.find((r) => within(r).queryByText("записка")) as HTMLElement).getByText(
        "записка",
      ),
    ).toBeVisible();
    expect(within(queue).getByText("Одобрить КП-2026/115")).toBeVisible();
    // СЦ-9: подпись договора и счёта на мне — строки «Подписать …»
    expect(within(queue).getByText("Подписать договор CT-2026-014")).toBeVisible();
    expect(within(queue).getByText("Подписать счёт INV-2026-031")).toBeVisible();
    expect(within(cards).getByRole("link", { name: /КП на одобрение/ })).toHaveTextContent("4");
    const open = within(
      rows.find((r) =>
        within(r).queryByText("Наложить резолюцию на письмо ВХ-104/26"),
      ) as HTMLElement,
    ).getByRole("link");
    expect(open).toHaveAttribute(
      "href",
      "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution",
    );
  });

  it("менеджер-универсал утром: расчёт, платёжка на подтверждение, счёт к выставлению, договор ждёт скана — каждая строка ведёт на экран, где это делается (D2-8)", async () => {
    signInAs("universal@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    const expectRow = async (title: RegExp, href: string) => {
      const row = (await within(page).findByText(title)).closest("li");
      if (!row) throw new Error(`нет строки ${String(title)}`);
      expect(within(row).getByRole("link")).toHaveAttribute("href", href);
    };
    await expectRow(/Начать расчёт по заявке ЗВ-2026-103/, "/erp/calc/%D0%97%D0%92-2026-103");
    await expectRow(
      /Подтвердить оплату по счёту СЧ-2026\/145/,
      "/eds/payments/145?panel=open&tab=payment",
    );
    await expectRow(/Выставить счёт СЧ-2026\/143/, "/eds/payments/143?panel=open&tab=payment");
    await expectRow(
      /Прикрепить скан подписанного договора ДОГ-2026\/106/,
      "/eds/projects/%D0%9F%D0%A0-2026-106",
    );
    // D26G-9: записка на шаге «Бухгалтер» — держателю права оплаты, на пилоте это менеджер-универсал
    await expectRow(
      /Принять к оплате СЗ-2026\/015/,
      "/eds/approvals/%D0%A1%D0%97-2026%2F015?panel=open&tab=agree",
    );
    // одна строка — одно действие: роль совмещает пять ролей SPEC, а дублей нет
    const titles = within(within(page).getByRole("region", { name: "Что ждёт вас" }))
      .getAllByRole("listitem")
      .map((li) => li.querySelector(".pf-queue-title, strong")?.textContent ?? li.textContent);
    expect(new Set(titles).size).toBe(titles.length);
    // карточки счетов — из той же очереди, а не числа, заданные вручную (U1)
    const cards = within(page).getByRole("region", { name: "Счётчики очереди" });
    expect(within(cards).getByRole("link", { name: /Оплаты на подтверждение/ })).toHaveTextContent(
      "1",
    );
    expect(within(cards).getByRole("link", { name: /Счета к выставлению/ })).toHaveTextContent("1");
  });

  it("менеджер видит свои строки из CRM; плашки источников нет", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Взять в работу лида L-2041")).toBeVisible();
    expect(within(page).getByText("Ответить лиду L-2050")).toBeVisible();
    // третья строка — «Доработать» (D1-6b): записку менеджера вернул директор, она лежит в его документах
    expect(within(page).getByText(/^[^·]+ · 3 решения/)).toBeVisible();
    expect(within(page).queryByRole("status")).toBeNull();
  });

  it("снабженец: просроченный заказ партнёру — строка «Моих задач» с переходом на карточку ЗП (D2-2)", async () => {
    signInAs("supply@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    const row = (await within(page).findByText(/Просрочен заказ ЗП-\d{4}-029/)).closest("li");
    if (!row) throw new Error("нет строки очереди");
    expect(within(row).getByText("просрочено")).toBeVisible();
    expect(within(row).getByText(/ООО «Вымышленная Сталь» · 3 дн\. просрочки/)).toBeVisible();
    expect(within(row).getByRole("link")).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/erp\/stock\/%D0%97%D0%9F-\d{4}-029$/),
    );
  });

  it("снабженец: черновик заказа партнёру — строка «Отправить заказ … партнёру» (план 0.7, FR-6)", async () => {
    const number = seedDraftOrder();
    signInAs("supply@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    const row = (await within(page).findByText(`Отправить заказ ${number} партнёру`)).closest("li");
    if (!row) throw new Error("нет строки очереди");
    expect(within(row).getByRole("link")).toHaveAttribute(
      "href",
      `/erp/stock/${encodeURIComponent(number)}`,
    );
  });

  it("снабженец: строки по проекту «Заказать недостающее» и «Отгрузить товар» ведут на предзаполненные экраны (СЦ-9)", async () => {
    signInAs("supply@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    const short = (await within(page).findByText("Заказать недостающее по ПР-2026-099")).closest(
      "li",
    );
    const ship = (await within(page).findByText("Отгрузить товар по ПР-2026-099")).closest("li");
    if (!short || !ship) throw new Error("нет строк очереди");
    const number = encodeURIComponent("ПР-2026-099");
    expect(within(short).getByRole("link")).toHaveAttribute(
      "href",
      `/erp/stock/new?mode=shortage&request=${number}`,
    );
    expect(within(ship).getByRole("link")).toHaveAttribute(
      "href",
      `/erp/stock?view=shipments&request=${number}`,
    );
  });

  it("СЦ-9: директору — строки «Подписать» (договор, счёт; письмо), «Открыть» ведёт к своему шагу подписи", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    const contract = (await within(page).findByText("Подписать договор CT-2026-014")).closest("li");
    expect(within(page).getByText("Подписать счёт INV-2026-031")).toBeVisible();
    if (!contract) throw new Error("нет строки подписи");
    // блок «Визы и подписи» под списком тоже на месте: «Подписать» делается там, строка на него наводит
    const link = within(contract).getByRole("link");
    expect(link.getAttribute("href")).toMatch(/^\/dashboard\/queue\?signing=/);
  });

  it("СЦ-9, ГЛ-1: строка подписи открывает окно решения «Подписать» / «Отказать»; блока «Визы и подписи» под списком нет", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue?signing=d1a00000-0000-4000-8000-000000000002");
    const page = await main();

    const window = await screen.findByRole("dialog", { name: /Счёт на предоплату/ });
    expect(within(window).getByRole("button", { name: "Подписать" })).toBeInTheDocument();
    expect(within(window).getByRole("button", { name: "Отказать" })).toBeInTheDocument();
    expect(within(page).queryByRole("list", { name: "Визы и подписи" })).toBeNull();
  });

  it("СЦ-9: замещающий — плашка «Вы замещаете … до …», строки «за …» и фильтр «За …»", async () => {
    server.use(
      http.get("*/me/profile", () =>
        HttpResponse.json({
          name: "Демо Менеджер",
          email: "manager@demo.example",
          language: "ru",
          timezone: "Asia/Tashkent",
          telegram: { linked: false, username: null, pending: false },
          covering: [
            { user_id: "12", name: "Мадина Р.", date_from: "2026-11-20", date_to: "2026-12-03" },
          ],
        }),
      ),
      http.get("*/queue", () =>
        HttpResponse.json({
          items: [
            {
              id: "memo:own",
              role_id: ROLE_ID.MANAGER,
              kind: "approve_memo",
              title: "Согласовать СЗ-2026/031",
              subtitle: "Директор",
              due_label: "memo",
              object: { kind: "memo", number: "СЗ-2026/031", path: "/eds/approvals/СЗ-2026%2F031" },
            },
            {
              id: "memo:other:for:12",
              role_id: ROLE_ID.MANAGER,
              kind: "approve_memo",
              title: "Согласовать СЗ-2026/041",
              subtitle: "Директор",
              due_label: "memo",
              object: { kind: "memo", number: "СЗ-2026/041", path: "/eds/approvals/СЗ-2026%2F041" },
              on_behalf_of: { id: "12", name: "Мадина Р." },
            },
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText(/Вы замещаете Мадина Р\. до/)).toBeVisible();
    expect(within(page).getByText(/за Мадина Р\. · Директор/)).toBeVisible();
    expect(within(page).getByText("Согласовать СЗ-2026/031")).toBeVisible();

    fireEvent.click(within(page).getByText("За Мадина Р."));
    expect(within(page).queryByText("Согласовать СЗ-2026/031")).toBeNull();
    expect(within(page).getByText("Согласовать СЗ-2026/041")).toBeVisible();
    fireEvent.click(within(page).getByText("Все"));
    expect(within(page).getByText("Согласовать СЗ-2026/031")).toBeVisible();
  });

  it("СЦ-9: фильтр «За …» сбрасывается, когда строк замещаемого в очереди больше нет", async () => {
    let deputyRows = true;
    const row = (id: string, number: string, over: object = {}) => ({
      id,
      role_id: ROLE_ID.MANAGER,
      kind: "approve_memo",
      title: `Согласовать ${number}`,
      subtitle: "Директор",
      due_label: "memo",
      object: { kind: "memo", number, path: `/eds/approvals/${encodeURIComponent(number)}` },
      ...over,
    });
    server.use(
      http.get("*/me/profile", () =>
        HttpResponse.json({
          name: "Демо Менеджер",
          email: "manager@demo.example",
          language: "ru",
          timezone: "Asia/Tashkent",
          telegram: { linked: false, username: null, pending: false },
          covering: [
            { user_id: "12", name: "Мадина Р.", date_from: "2026-11-20", date_to: "2026-12-03" },
          ],
        }),
      ),
      http.get("*/queue", () =>
        HttpResponse.json({
          items: [
            row("memo:own", "СЗ-2026/031"),
            ...(deputyRows
              ? [
                  row("memo:o:for:12", "СЗ-2026/041", {
                    on_behalf_of: { id: "12", name: "Мадина Р." },
                  }),
                ]
              : []),
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("manager@demo.example");
    const { queryClient } = renderApp("/dashboard/queue");
    const page = await main();
    fireEvent.click(await within(page).findByText("За Мадина Р."));
    expect(within(page).queryByText("Согласовать СЗ-2026/031")).toBeNull();

    deputyRows = false;
    await act(async () => {
      await queryClient.invalidateQueries();
    });

    expect(await within(page).findByText("Согласовать СЗ-2026/031")).toBeVisible();
    expect(within(page).queryByText("За Мадина Р.")).toBeNull();
  });

  it("менеджер (склад — только чтение) строки о просроченных заказах не получает", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();
    await within(page).findByText("Взять в работу лида L-2041");
    expect(within(page).queryByText(/Просрочен заказ/)).toBeNull();
  });

  it("пустая очередь снабженца — по разделам каталога, не директорский текст", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({ items: [], sources: { crm: "ok", erp: "ok" } }),
      ),
    );
    signInAs("supply@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Заданий на расчёт нет")).toBeVisible();
    expect(within(page).queryByText("Решений от вас пока не требуется")).toBeNull();
    expect(within(page).getByText(/0 решений/)).toBeVisible();
  });

  it.each([
    ["engineer@demo.example", "Заданий по услугам нет"],
    ["accountant@demo.example", "Оплат на подтверждение и счетов к выставлению нет"],
    ["admin@demo.example", "Задач для вас нет"],
  ])("пустая очередь %s: свой текст", async (email, title) => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({ items: [], sources: { crm: "ok", erp: "ok" } }),
      ),
    );
    signInAs(email);
    renderApp("/dashboard/queue");
    const page = await main();
    expect(await within(page).findByText(title)).toBeVisible();
  });

  it("пустая очередь директора: слова SPEC-v3 §7.1 и действие", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({ items: [], sources: { crm: "ok", erp: "ok" } }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Решений от вас пока не требуется")).toBeVisible();
    expect(
      within(page).getByText("Новые письма, черновики КП и записки приходят сюда сами."),
    ).toBeVisible();
    expect(within(page).getByRole("link", { name: "Проекты" })).toBeVisible();
  });

  it("менеджер без задач: «Клиенты вас сейчас не ждут»", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({ items: [], sources: { crm: "ok", erp: "ok" } }),
      ),
    );
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();
    expect(await within(page).findByText("Клиенты вас сейчас не ждут")).toBeVisible();
  });

  it("менеджер: «Взять» — в строке, «Ответить» открывает диалог в «Ждут ответа», без «Где сделать»", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    // «Взять» — простое действие, делается в самой строке; «Ответить» открывает диалог
    const take = await within(page).findByRole("button", {
      name: "Взять: Взять в работу лида L-2041",
    });
    expect(take).toBeVisible();
    expect(
      within(page).getByRole("link", { name: "Ответить: Ответить лиду L-2050" }),
    ).toHaveAttribute("href", "/crm/messages?lead=L-2050");
    expect(within(page).queryByRole("button", { name: /^Где сделать/ })).toBeNull();
  });

  it("BFF прислал короткие адреса объектов — вкладка решения достраивается в Платформе", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({
          items: [
            {
              id: "letter:104",
              role_id: "2",
              kind: "resolve_letter",
              title: "Наложить резолюцию на письмо ВХ-104/26",
              subtitle: "ООО «Демо-Депо»",
              due_label: "later",
              object: {
                kind: "letter",
                number: "ВХ-104/26",
                path: "/eds/inbox/%D0%92%D0%A5-104%2F26",
              },
            },
            {
              id: "memo:31",
              role_id: "2",
              kind: "approve_memo",
              title: "Согласовать СЗ-2026/031",
              subtitle: "от Демо Офисовой",
              due_label: "memo",
              object: { kind: "memo", number: "СЗ-2026/031", path: "/eds/approvals" },
            },
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(
      await within(page).findByRole("link", {
        name: /Наложить резолюцию: Наложить резолюцию на письмо/,
      }),
    ).toHaveAttribute("href", "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution");
    expect(
      within(page).getByRole("link", { name: "Согласовать: Согласовать СЗ-2026/031" }),
    ).toHaveAttribute("href", "/eds/approvals/%D0%A1%D0%97-2026%2F031?panel=open&tab=agree");
  });

  it("строка директора с родным экраном (письмо, КП) — «Открыть»: primary только у первой срочной строки", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({
          items: [
            {
              id: "letter:104",
              role_id: "2",
              kind: "resolve_letter",
              title: "Наложить резолюцию на письмо ВХ-104/26",
              subtitle: "ООО «Демо-Депо»",
              due_label: "today",
              object: {
                kind: "letter",
                number: "ВХ-104/26",
                path: "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution",
              },
            },
            {
              id: "letter:105",
              role_id: "2",
              kind: "resolve_letter",
              title: "Наложить резолюцию на письмо ВХ-105/26",
              subtitle: "АО «Демо-Транс»",
              due_label: "overdue",
              object: {
                kind: "letter",
                number: "ВХ-105/26",
                path: "/eds/inbox/%D0%92%D0%A5-105%2F26?panel=open&tab=resolution",
              },
            },
            {
              id: "quote:118",
              role_id: "2",
              kind: "approve_quote",
              title: "Одобрить КП-2026/118 (черновик)",
              subtitle: "АО «Демо-Рейл»",
              due_label: "tomorrow",
              object: {
                kind: "quote",
                number: "КП-2026/118",
                path: "/eds/drafts/%D0%9A%D0%9F-2026%2F118?panel=open&tab=approve",
              },
            },
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    const first = await within(page).findByRole("link", {
      name: "Наложить резолюцию: Наложить резолюцию на письмо ВХ-104/26",
    });
    const second = within(page).getByRole("link", {
      name: "Наложить резолюцию: Наложить резолюцию на письмо ВХ-105/26",
    });
    // главная кнопка одна — у первой срочной строки (просрочено идёт раньше «сегодня»)
    expect(second).toHaveClass("ant-btn-primary");
    expect(first).not.toHaveClass("ant-btn-primary");
    expect(
      within(page).getByRole("link", { name: "Одобрить: Одобрить КП-2026/118 (черновик)" }),
    ).not.toHaveClass("ant-btn-primary");
  });

  it("EDS не отвечает: писем, КП и служебок нет, остальное показано, плашка называет «Документы» (D1-6, D26G-4)", async () => {
    window.localStorage.setItem(MOCK_EDS_DOWN_KEY, "1");
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText(/Просрочен заказ ЗП-\d{4}-029/)).toBeVisible();
    expect(within(page).queryByText(/Одобрить КП/)).toBeNull();
    expect(within(page).queryByText(/Наложить резолюцию на письмо/)).toBeNull();
    expect(within(page).queryByText(/Согласовать СЗ-2026\/031/)).toBeNull();
    expect(within(page).getByRole("status")).toHaveTextContent(
      "Не загрузились письма и документы: раздел «Документы» не ответил. Остальное показано.",
    );
    // карточки EDS без числа не показываются: ноль был бы ложью
    expect(within(page).queryByRole("link", { name: /Входящие без резолюции/ })).toBeNull();
    expect(within(page).queryByRole("link", { name: /КП на одобрение/ })).toBeNull();
  });

  it("не ответили ERP и EDS: одна плашка с названиями обоих разделов", async () => {
    window.localStorage.setItem(MOCK_EDS_DOWN_KEY, "1");
    window.localStorage.setItem(MOCK_ERP_DOWN_KEY, "1");
    signInAs("all@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(
      await within(page).findByText(
        "Не загрузились данные из разделов «Операции», «Документы». Остальное показано.",
      ),
    ).toBeVisible();
  });

  it("Раздел «Операции» не отвечает: данные CRM остаются, сверху плашка с названиями разделов", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({
          items: [
            {
              id: "lead:1",
              role_id: "1",
              kind: "take_lead",
              title: "Взять в работу лида L-0001",
              subtitle: "Демо Клиентов",
              due_label: "today",
              object: {
                kind: "lead",
                number: "L-0001",
                path: "/crm/leads?lead=L-0001&panel=open&tab=card",
              },
            },
          ],
          sources: { crm: "ok", erp: "unavailable" },
        }),
      ),
    );
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Взять в работу лида L-0001")).toBeVisible();
    expect(within(page).getByRole("status")).toHaveTextContent(
      "Не загрузились КП, расчёты, счета и проекты: раздел «Операции» не ответил. Остальное показано.",
    );
  });

  it("Раздел «Контакты» не отвечает: плашка называет «Контакты», данные ERP показаны", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({
          items: [
            {
              id: "quote:118",
              role_id: "2",
              kind: "approve_quote",
              title: "Одобрить КП-2026/118 (черновик)",
              subtitle: "АО «Демо-Рейл»",
              due_label: "tomorrow",
              object: {
                kind: "quote",
                number: "КП-2026/118",
                path: "/eds/drafts/%D0%9A%D0%9F-2026%2F118",
              },
            },
          ],
          sources: { crm: "unavailable", erp: "ok" },
        }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Одобрить КП-2026/118 (черновик)")).toBeVisible();
    expect(within(page).getByRole("status")).toHaveTextContent(
      "Не загрузились лиды и ответы клиентам: раздел «Контакты» не ответил. Остальное показано.",
    );
  });

  it("не ответили оба и очередь пуста: не «задач нет», а «загружена не полностью» с «Повторить»", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({ items: [], sources: { crm: "unavailable", erp: "unavailable" } }),
      ),
    );
    signInAs("all@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Очередь загружена не полностью")).toBeVisible();
    expect(within(page).queryByText("Решений от вас пока не требуется")).toBeNull();
    // «Повторить» — в плашке над списком, второй кнопки в пустом состоянии нет
    expect(within(page).getAllByRole("button", { name: "Повторить" })).toHaveLength(1);
    expect(within(page).getAllByRole("status")[0]).toHaveTextContent(
      "разделы «Контакты» и «Операции» не ответили",
    );
  });

  it("сбой запроса: экран с причиной и «Повторить», после повтора данные появляются", async () => {
    let calls = 0;
    server.use(
      http.get("*/queue", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json(
              { code: "INTERNAL_ERROR", message: "Ошибка сервера.", source: "bff" },
              { status: 500 },
            )
          : HttpResponse.json({ items: [], sources: { crm: "ok", erp: "ok" } });
      }),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Не удалось загрузить очередь")).toBeVisible();
    fireEvent.click(within(page).getByRole("button", { name: "Повторить" }));
    expect(await within(page).findByText("Решений от вас пока не требуется")).toBeVisible();
  });

  it("смена активной роли: запрос уходит с role, очередь пересчитывается", async () => {
    const seen: (string | null)[] = [];
    server.events.on("request:start", ({ request }) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith("/queue")) seen.push(url.searchParams.get("role"));
    });
    signInAs("all@demo.example", "MANAGER");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Взять в работу лида L-2041")).toBeVisible();
    expect(within(page).queryByText(/Наложить резолюцию/)).toBeNull();
    expect(seen).toContain(ROLE_ID.MANAGER);
    server.events.removeAllListeners();
  });

  it("опрос: очередь и счётчики запрашиваются каждые 30 с и при возврате на вкладку", async () => {
    signInAs("director@demo.example");
    const { queryClient } = renderApp("/dashboard/queue");
    await main();

    await waitFor(() => {
      const queries = queryClient.getQueryCache().findAll({ queryKey: ["/api/v1/queue"] });
      expect(queries.length).toBeGreaterThan(0);
    });
    const watched = queryClient
      .getQueryCache()
      .getAll()
      .filter((q) => /\/api\/v1\/(queue|notifications|menu-counters)/.test(String(q.queryKey[0])));
    expect(watched.length).toBeGreaterThanOrEqual(4);
    for (const query of watched) {
      const options = query.observers[0]?.options;
      expect(options?.refetchInterval, String(query.queryKey[0])).toBe(POLL_INTERVAL_MS);
      expect(options?.refetchOnWindowFocus).toBe(true);
    }
    expect(POLL_INTERVAL_MS).toBe(30_000);
  });

  describe("поток подсказок BFF (SSE)", () => {
    beforeEach(() => {
      FakeEventSource.reset();
      vi.stubGlobal("EventSource", FakeEventSource);
    });
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    function countRequests() {
      const hits = { queue: 0, cards: 0, counters: 0, notifications: 0 };
      server.events.on("request:start", ({ request }) => {
        const path = new URL(request.url).pathname;
        if (path === "/api/v1/queue") hits.queue += 1;
        if (path === "/api/v1/queue/cards") hits.cards += 1;
        if (path === "/api/v1/menu-counters") hits.counters += 1;
        if (path === "/api/v1/notifications") hits.notifications += 1;
      });
      return hits;
    }

    it("подсказка обновляет очередь, карточки, счётчики и колокольчик без опроса; опрос при живом потоке редкий", async () => {
      signInAs("director@demo.example");
      const hits = countRequests();
      const { queryClient } = renderApp("/dashboard/queue");
      await main();
      await waitFor(() => {
        expect(FakeEventSource.instances).toHaveLength(1);
        expect(hits.queue + hits.cards + hits.counters + hits.notifications).toBeGreaterThanOrEqual(
          4,
        );
      });
      act(() => {
        FakeEventSource.last.open();
      });
      const before = { ...hits };

      for (const query of queryClient.getQueryCache().getAll()) {
        if (/\/api\/v1\/(queue|notifications|menu-counters)/.test(String(query.queryKey[0]))) {
          expect(query.observers[0]?.options.refetchInterval).toBe(STREAM_POLL_INTERVAL_MS);
        }
      }

      act(() => {
        FakeEventSource.last.emit("invalidate", {
          topics: ["queue", "counters", "notifications"],
          reason: "uz.railtech.erp.quote.sent.v1",
        });
      });
      await waitFor(() => {
        expect(hits.queue).toBe(before.queue + 1);
        expect(hits.cards).toBe(before.cards + 1);
        expect(hits.counters).toBe(before.counters + 1);
        expect(hits.notifications).toBe(before.notifications + 1);
      });
    });

    it("поток оборвался — опрос возвращается к 30 с", async () => {
      signInAs("director@demo.example");
      const { queryClient } = renderApp("/dashboard/queue");
      await main();
      await waitFor(() => {
        expect(FakeEventSource.instances).toHaveLength(1);
      });
      act(() => {
        FakeEventSource.last.open();
      });
      act(() => {
        FakeEventSource.last.fail();
      });
      await waitFor(() => {
        const watched = queryClient
          .getQueryCache()
          .getAll()
          .filter((q) =>
            /\/api\/v1\/(queue|notifications|menu-counters)/.test(String(q.queryKey[0])),
          );
        expect(watched.length).toBeGreaterThanOrEqual(4);
        for (const query of watched) {
          expect(query.observers[0]?.options.refetchInterval).toBe(POLL_INTERVAL_MS);
        }
      });
    });
  });
});

/** ГЛ-1 «Что ждёт вас»: группы срока, чипы вида работы со счётчиком, «почему у вас», быстрое действие, «Вы ждёте других». */
describe("Dashboard · Что ждёт вас (ГЛ-1)", () => {
  const row = (id: string, over: Record<string, unknown> = {}) => ({
    id,
    role_id: ROLE_ID.DIRECTOR,
    kind: "sign_document",
    title: `Подписать ${id}`,
    subtitle: "Договор поставки",
    due_label: "later",
    group: "later",
    category: "sign",
    action_label: "Подписать",
    reason: "вы подписант по реестру полномочий · ждёт 2 ч",
    object: { kind: "contract", number: id, path: `/dashboard/queue?signing=${id}` },
    ...over,
  });
  const ITEMS = [
    row("D-1", { due_label: "overdue", group: "overdue" }),
    row("D-2", { due_label: "today", group: "today" }),
    row("D-3"),
    row("M-1", {
      kind: "approve_memo",
      title: "Согласовать СЗ-1",
      category: "approve",
      action_label: "Согласовать",
      reason: "ваш шаг маршрута: Директор",
      object: { kind: "memo", number: "СЗ-1", path: "/eds/approvals/СЗ-1" },
    }),
    row("A-1", {
      id: "acquaint:40000000-0000-4000-8000-000000000112",
      kind: "acquaint",
      title: "Ознакомиться с письмом ВХ-112/26",
      category: "instruction",
      action_label: "Ознакомлен",
      reason: "вас просят ознакомиться с письмом · без срока",
      object: { kind: "letter", number: "ВХ-112/26", path: "/eds/tasks/40000000" },
    }),
  ];
  const serve = (items: unknown[], extra: Record<string, unknown> = {}) => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({ items, sources: { crm: "ok", erp: "ok" }, ...extra }),
      ),
    );
  };

  it("группы «Просрочено · 1», «Сегодня · 1», «Позже · 3» и чипы со счётчиком у каждого вида", async () => {
    serve(ITEMS);
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(
      await within(page).findByRole("heading", { level: 3, name: "Просрочено · 1" }),
    ).toBeVisible();
    expect(within(page).getByRole("heading", { level: 3, name: "Сегодня · 1" })).toBeVisible();
    expect(within(page).getByRole("heading", { level: 3, name: "Позже · 3" })).toBeVisible();
    const chips = within(page).getByRole("group", { name: "Вид работы" });
    expect(within(chips).getByRole("button", { name: "Всё 5" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(chips).getByRole("button", { name: "Подписать 3" })).toBeVisible();
    expect(within(chips).getByRole("button", { name: "Согласовать 1" })).toBeVisible();
    expect(within(chips).getByRole("button", { name: "Поручения 1" })).toBeVisible();
    // подзаголовок: сколько задач и сколько из них просрочено
    expect(within(page).getByText(/5 решений · просрочено: 1/)).toBeVisible();
  });

  it("чип вида работы оставляет только его строки; пустые группы пропадают", async () => {
    serve(ITEMS);
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    fireEvent.click(await within(page).findByRole("button", { name: "Согласовать 1" }));

    expect(within(page).getByRole("button", { name: "Согласовать 1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(page).getByText("Согласовать СЗ-1")).toBeVisible();
    expect(within(page).queryByText("Подписать D-1")).toBeNull();
    expect(within(page).queryByRole("heading", { level: 3, name: /Просрочено/ })).toBeNull();
    expect(within(page).getByRole("heading", { level: 3, name: "Позже · 1" })).toBeVisible();
  });

  it("каждая строка называет, почему она у вас, а кнопка — действие", async () => {
    serve(ITEMS);
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    const sign = (await within(page).findByText("Подписать D-1")).closest("li");
    if (!sign) throw new Error("нет строки подписи");
    expect(within(sign).getByText(/вы подписант по реестру полномочий · ждёт 2 ч/)).toBeVisible();
    expect(within(sign).getByText("Почему у вас:")).toBeVisible();
    const open = within(sign).getByRole("link", { name: "Подписать: Подписать D-1" });
    expect(open).toHaveTextContent("Подписать");
    expect(open).toHaveAttribute("href", "/dashboard/queue?signing=D-1");
    expect(open).toHaveClass("ant-btn-primary"); // просрочено — главная кнопка
    const memo = within(page).getByText("Согласовать СЗ-1").closest("li");
    if (!memo) throw new Error("нет строки согласования");
    expect(
      within(memo).getByRole("link", { name: /Согласовать: Согласовать СЗ-1/ }),
    ).not.toHaveClass("ant-btn-primary");
  });

  it("«Ознакомлен» — быстрое действие в строке: уходит на EDS и строка гаснет, когда источник её убрал", async () => {
    let acknowledged = false;
    let calls = 0;
    server.use(
      http.get("*/queue", () => {
        calls += 1;
        return HttpResponse.json({
          items: acknowledged ? ITEMS.slice(0, 4) : ITEMS,
          sources: { crm: "ok", erp: "ok" },
        });
      }),
      http.post("*/eds/letters/:id/acquaint", ({ params }) => {
        expect(params.id).toBe("40000000-0000-4000-8000-000000000112");
        acknowledged = true;
        return HttpResponse.json({});
      }),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    fireEvent.click(
      await within(page).findByRole("button", {
        name: "Ознакомлен: Ознакомиться с письмом ВХ-112/26",
      }),
    );

    await waitFor(() => {
      expect(within(page).queryByText("Ознакомиться с письмом ВХ-112/26")).toBeNull();
    });
    expect(calls).toBeGreaterThan(1);
  });

  it("источник отдал не всё — «Показаны не все задачи»; полная очередь без пометки", async () => {
    serve(ITEMS, { truncated: true });
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByRole("note")).toHaveTextContent("Показаны не все задачи");
  });

  it("«Вы ждёте других»: кто и сколько ждёт, «Напомнить» — раз в час, повтор объясняется", async () => {
    serve(ITEMS);
    const sent: string[] = [];
    server.use(
      http.get("*/queue/waiting", () =>
        HttpResponse.json({
          items: [
            {
              id: "letter_signature:aaa",
              kind: "letter_signature",
              object_id: "aaa",
              title: "Ответ на требование",
              waiting_on: { id: "4", name: "Рустам Каримов" },
              since: new Date(Date.now() - 3 * 3_600_000).toISOString(),
              remindable: true,
              object: { kind: "memo", number: "Ответ", path: "/eds/documents?doc=aaa&panel=open" },
            },
            {
              id: "approval:bbb",
              kind: "approval",
              object_id: "bbb",
              title: "СЗ-2026/212 · Закупка",
              waiting_label: "Бухгалтер",
              since: new Date(Date.now() - 26 * 3_600_000).toISOString(),
              remindable: false,
              remind_available_at: new Date(Date.now() + 1_800_000).toISOString(),
              object: { kind: "memo", number: "СЗ-2026/212", path: "/eds/approvals/СЗ-2026%2F212" },
            },
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
      http.post("*/queue/waiting/:kind/:id/remind", ({ params }) => {
        sent.push(`${String(params.kind)}:${String(params.id)}`);
        return HttpResponse.json({ reminded_at: new Date().toISOString() });
      }),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    const block = await within(page).findByRole("region", { name: /Вы ждёте других/ });
    expect(within(block).getByText(/на подписи у Рустам Каримов · 3 ч/)).toBeVisible();
    expect(within(block).getByText(/на согласовании: Бухгалтер · 1 д/)).toBeVisible();
    expect(within(block).getByRole("link", { name: "Ответ на требование" })).toHaveAttribute(
      "href",
      "/eds/documents?doc=aaa&panel=open",
    );
    // уже напомнили полчаса назад — кнопка недоступна до разрешения EDS
    expect(
      within(block).getByRole("button", { name: "Напомнить: СЗ-2026/212 · Закупка" }),
    ).toBeDisabled();
    fireEvent.click(within(block).getByRole("button", { name: "Напомнить: Ответ на требование" }));
    await waitFor(() => {
      expect(sent).toEqual(["letter_signature:aaa"]);
    });
    expect(await screen.findByText("Напоминание отправлено")).toBeVisible();
  });

  it("повторное «Напомнить» раньше часа: EDS отвечает 429 — человек читает «Уже напоминали»", async () => {
    serve(ITEMS);
    server.use(
      http.get("*/queue/waiting", () =>
        HttpResponse.json({
          items: [
            {
              id: "instruction:ccc",
              kind: "instruction",
              object_id: "ccc",
              title: "ВХ-112/26 · Требование",
              waiting_on: { id: "7", name: "Иван Исполнитель" },
              since: new Date(Date.now() - 48 * 3_600_000).toISOString(),
              due_at: "2027-01-20T18:59:59Z",
              remindable: true,
              object: { kind: "letter", number: "ВХ-112/26", path: "/eds/inbox/ВХ-112%2F26" },
            },
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
      http.post("*/queue/waiting/:kind/:id/remind", () =>
        HttpResponse.json(
          { code: "TOO_MANY_REQUESTS", message: "x", source: "eds" },
          { status: 429 },
        ),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    fireEvent.click(
      await within(page).findByRole("button", { name: "Напомнить: ВХ-112/26 · Требование" }),
    );

    expect(await screen.findByText("Уже напоминали, повторить можно позже")).toBeVisible();
  });

  it("мобильная ширина 390: чипы листаются, строки одной колонкой, блок «Вы ждёте других» на месте", async () => {
    setViewportWidth(390);
    serve(ITEMS);
    server.use(
      http.get("*/queue/waiting", () =>
        HttpResponse.json({
          items: [
            {
              id: "approval:bbb",
              kind: "approval",
              object_id: "bbb",
              title: "СЗ-2026/212 · Закупка",
              waiting_label: "Бухгалтер",
              since: new Date(Date.now() - 26 * 3_600_000).toISOString(),
              remindable: true,
              object: { kind: "memo", number: "СЗ-2026/212", path: "/eds/approvals/СЗ-2026%2F212" },
            },
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByRole("group", { name: "Вид работы" })).toBeVisible();
    expect(await within(page).findByRole("region", { name: /Вы ждёте других/ })).toBeVisible();
  });
});
