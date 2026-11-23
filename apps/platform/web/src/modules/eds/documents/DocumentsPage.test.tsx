import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";
import { panelEl, renderAt, setupEdsTests, signIn } from "../../../test/edsKit";
import { listSettled } from "../../../test/settled";
import { readEds, writeEds } from "../../../mocks/fixtures/edsDocuments";
import { companyDayIn } from "../../../mocks/fixtures/dates";
import { formatDate } from "../../../shared/lib/dates";

setupEdsTests();

async function openDocuments(email: string, search = "") {
  signIn(email);
  const view = renderAt(`/eds/documents${search}`);
  expect(await screen.findByRole("heading", { level: 1, name: "Все документы" })).toBeVisible();
  return view;
}

function row(subject: string): HTMLElement {
  const link = screen.getByRole("link", { name: `Открыть документ: ${subject}` });
  const tr = link.closest("tr");
  if (!tr) throw new Error(`нет строки ${subject}`);
  return tr;
}

describe("EDS · Документы: список", () => {
  it("менеджер: «Мои» — только свои документы со статусом словами, суммой и сроком; «Продолжить» у черновика и возврата", async () => {
    await openDocuments("manager@demo.example", "?scope=mine");

    expect(
      await screen.findByRole("link", { name: "Открыть документ: Закупка канцтоваров на квартал" }),
    ).toBeVisible();
    expect(
      within(row("Закупка канцтоваров на квартал")).getByText("На согласовании"),
    ).toBeVisible();
    expect(within(row("Закупка канцтоваров на квартал")).getByText("4 800 000 сум")).toBeVisible();
    expect(
      within(row("Закупка канцтоваров на квартал")).getByText(formatDate(companyDayIn(7))),
    ).toBeVisible();
    expect(
      within(row("Командировка в Самарканд")).getByText("Возвращена на доработку"),
    ).toBeVisible();
    expect(within(row("Заявление на ежегодный отпуск")).getByText("Согласована")).toBeVisible();
    expect(within(row("Ремонт кондиционера в переговорной")).getByText("Черновик")).toBeVisible();
    expect(
      within(row("Ремонт кондиционера в переговорной")).getByRole("link", {
        name: "Продолжить документ: Ремонт кондиционера в переговорной",
      }),
    ).toHaveAttribute("href", "/eds/new?draft=00000000-0000-4000-8000-000000000004");
    expect(
      within(row("Командировка в Самарканд")).getByRole("link", { name: /Продолжить/ }),
    ).toBeVisible();
    expect(
      within(row("Закупка канцтоваров на квартал")).queryByRole("link", { name: /Продолжить/ }),
    ).toBeNull();
    // чужих документов («Заказ спецодежды» снабженца) и писем здесь нет
    expect(screen.queryByText("Заказ спецодежды для бригады")).toBeNull();
    expect(screen.queryByText("Запрос цен на рельсы Р65")).toBeNull();
  });

  it("ЕВ-3а: «Шаблоны» ушли из меню «Документов» — ссылка на экране только у директора (право на шаблоны компании)", async () => {
    await openDocuments("director@demo.example");
    expect(await screen.findByRole("link", { name: "Шаблоны документов" })).toHaveAttribute(
      "href",
      "/admin/templates",
    );
    cleanup();
    await openDocuments("manager@demo.example");
    expect(screen.queryByRole("link", { name: "Шаблоны документов" })).toBeNull();
  });

  it("менеджер с доступом к входящим: по умолчанию реестр «Все» — чужие документы, письма и КП; письма и КП открываются своей карточкой", async () => {
    await openDocuments("manager@demo.example");

    expect(await screen.findByText("Запрос цен на рельсы Р65")).toBeVisible();
    expect(screen.getByText("Заказ спецодежды для бригады")).toBeVisible();
    expect(screen.getByText("КП · Монтаж стрелочных переводов")).toBeVisible();
    const letter = screen.getByText("Запрос цен на рельсы Р65").closest("tr") as HTMLElement;
    expect(within(letter).getByText("Ждёт резолюции")).toBeVisible();
    expect(within(letter).getByText("ВХ-104/26")).toBeVisible();
    // письмо открывается само, а не раздел «Входящие» (ДОК-8): и темой, и ссылкой в строке
    const href = `/eds/inbox/${encodeURIComponent("ВХ-104/26")}`;
    expect(
      within(letter).getByRole("link", { name: "Открыть письмо: Запрос цен на рельсы Р65" }),
    ).toHaveAttribute("href", href);
    expect(
      within(letter).getByRole("link", { name: "Открыть документ: Запрос цен на рельсы Р65" }),
    ).toHaveAttribute("href", href);
    expect(screen.getByRole("columnheader", { name: "Ответственный" })).toBeVisible();
  });

  it("вкладки по типу и фильтр статуса сужают список; вкладка КП есть только в реестре", async () => {
    await openDocuments("manager@demo.example", "?scope=mine");
    await screen.findByRole("link", { name: "Открыть документ: Закупка канцтоваров на квартал" });
    expect(screen.queryByRole("tab", { name: "КП" })).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Заявления" }));
    await listSettled();
    await waitFor(() => {
      expect(
        screen.queryByRole("link", { name: "Открыть документ: Закупка канцтоваров на квартал" }),
      ).toBeNull();
    });
    expect(
      await screen.findByRole("link", { name: "Открыть документ: Заявление на ежегодный отпуск" }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Служебные" }));
    await listSettled();
    fireEvent.mouseDown(screen.getByLabelText("Статус"));
    fireEvent.click(await screen.findByTitle("Черновик"));
    await listSettled();
    expect(
      await screen.findByRole("link", {
        name: "Открыть документ: Ремонт кондиционера в переговорной",
      }),
    ).toBeVisible();
    await waitFor(() => {
      expect(
        screen.queryByRole("link", { name: "Открыть документ: Закупка канцтоваров на квартал" }),
      ).toBeNull();
    });

    fireEvent.click(screen.getByRole("tab", { name: "Отчёты" }));
    await listSettled();
    expect(await screen.findByText("По этим условиям ничего нет")).toBeVisible();
  });

  it("реестр: вкладка КП показывает маршруты одобрения", async () => {
    await openDocuments("director@demo.example");

    fireEvent.click(await screen.findByRole("tab", { name: "КП" }));
    await listSettled();

    expect(await screen.findByText("КП · Монтаж стрелочных переводов")).toBeVisible();
    expect(screen.getByText("На одобрении")).toBeVisible();
    expect(screen.queryByText("Заказ спецодежды для бригады")).toBeNull();
  });

  it("реестр: договор и акт проекта — вкладки «Договоры» и «Акты», статус словами SPEC, ссылка «В проекте» ведёт в карточку проекта (D2-5)", async () => {
    await openDocuments("director@demo.example");

    fireEvent.click(await screen.findByRole("tab", { name: "Договоры" }));
    await listSettled();

    const contract = (await screen.findByText("Поставка стрелочных переводов")).closest(
      "tr",
    ) as HTMLElement;
    expect(within(contract).getByText("ДОГ-2026/105")).toBeVisible();
    expect(within(contract).getByText("Согласован клиентом")).toBeVisible();
    expect(
      within(contract).getByRole("link", {
        name: "Открыть в проекте: Поставка стрелочных переводов",
      }),
    ).toHaveAttribute("href", "/eds/projects/105");
    expect(screen.queryByText("Монтаж крепежа, объект «Север»")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Акты" }));
    await listSettled();
    const act = (await screen.findByText("Монтаж крепежа, объект «Север»")).closest(
      "tr",
    ) as HTMLElement;
    expect(within(act).getByText("Выпущен")).toBeVisible();
    expect(within(act).getByRole("link", { name: /Открыть в проекте/ })).toHaveAttribute(
      "href",
      "/eds/projects/97",
    );
    // Акт, принятый клиентом в Кабинете (EDS: `signed`), — без «скан»: реестр не знает о файле.
    const accepted = (await screen.findByText("Поставка крепежа, объект «Юг»")).closest(
      "tr",
    ) as HTMLElement;
    expect(within(accepted).getByText("Принят клиентом")).toBeVisible();
    expect(within(accepted).queryByText(/скан/)).toBeNull();
  });

  it("«Мои документы»: вкладок договоров, счетов и актов нет — они в реестре компании", async () => {
    await openDocuments("manager@demo.example", "?scope=mine");
    await screen.findByRole("link", { name: "Открыть документ: Закупка канцтоваров на квартал" });
    for (const name of ["Договоры", "Счета", "Акты"]) {
      expect(screen.queryByRole("tab", { name })).toBeNull();
    }
  });

  it("реестр отдаёт меньше прав на вид (D1-10): вкладка «Письма» без права на письма — пусто словами, не ошибка", async () => {
    // EDS без `letters.read` не включает письма в реестр: ответ 200 с пустой страницей
    server.use(
      http.get("*/eds/documents", ({ request }) => {
        const kinds = new URL(request.url).searchParams.getAll("kind");
        if (kinds.includes("letter_in")) return HttpResponse.json({ items: [], next_cursor: null });
        return undefined;
      }),
    );
    await openDocuments("manager@demo.example");

    fireEvent.click(await screen.findByRole("tab", { name: "Письма" }));
    await listSettled();

    expect(await screen.findByText("По этим условиям ничего нет")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Не удалось загрузить документы")).toBeNull();
  });

  it("снабженец (реестр через проекты, без входящих): вкладки «Письма» нет, `?kind=letters` — «Все»", async () => {
    await openDocuments("supply@demo.example", "?kind=letters");
    expect(await screen.findByRole("tab", { name: "Все типы", selected: true })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Служебные" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Письма" })).toBeNull();
  });

  it("администратор без доступа к реестру видит только «Мои», без переключателя; пусто — словами и с действием", async () => {
    await openDocuments("admin@demo.example", "?scope=all");

    expect(await screen.findByText("Своих документов пока нет")).toBeVisible();
    expect(screen.queryByRole("radiogroup", { name: "Чьи документы" })).toBeNull();
  });

  it("постраничный просмотр: «Дальше» берёт следующий курсор, «Назад» возвращает", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get("*/eds/documents", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        seen.push(cursor);
        const second = cursor === "page-2";
        return HttpResponse.json({
          items: [
            {
              kind: "memo",
              id: second
                ? "00000000-0000-4000-8000-0000000000b2"
                : "00000000-0000-4000-8000-0000000000b1",
              number: second ? "СЗ-2026/002" : "СЗ-2026/001",
              subject: second ? "Вторая страница" : "Первая страница",
              status: "on_approval",
              author: { crm_user_id: 1, full_name: "Демо Менеджеров" },
              amount: null,
              due_date: null,
              created_at: "2026-10-26T08:30:00Z",
              openable: true,
            },
          ],
          next_cursor: second ? null : "page-2",
        });
      }),
    );
    await openDocuments("admin@demo.example");

    expect(
      await screen.findByRole("link", { name: "Открыть документ: Первая страница" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Назад" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Дальше" }));
    expect(
      await screen.findByRole("link", { name: "Открыть документ: Вторая страница" }),
    ).toBeVisible();
    expect(screen.getByText("Страница 2")).toBeVisible();
    expect(screen.getByRole("button", { name: "Дальше" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Назад" }));
    expect(
      await screen.findByRole("link", { name: "Открыть документ: Первая страница" }),
    ).toBeVisible();
    expect(seen).toEqual([null, "page-2", null]);
  });

  it("сервис документов не отвечает: словами и с «Повторить»", async () => {
    server.use(
      http.get("*/eds/documents", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "x", source: "eds" },
          { status: 503 },
        ),
      ),
    );
    await openDocuments("manager@demo.example");

    expect(await screen.findByText("Документы недоступны")).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});

describe("EDS · Документы: письмо на подписи (СЦ-8)", () => {
  it("переданное письмо в списке — «На подписи», не переданное — «Черновик»", async () => {
    const state = readEds();
    const template = state.documents.find(
      (d) => d.ownerId === "u-demo-manager" && d.status === "draft",
    );
    if (!template) throw new Error("нет шаблона черновика");
    const letter = (n: number, subject: string, handed: boolean) => ({
      ...template,
      id: `00000000-0000-4000-8000-0000000009${String(n)}0`,
      kind: "letter_out" as const,
      subject,
      replyTo: null,
      letter: {
        body: null,
        recipient_attention: null,
        recipient_email: null,
        signatory_name: null,
        signatory_position: null,
        pdf: null,
        pdfPolls: 0,
        mailings: [],
        registration_requested: handed
          ? { ownerId: "u-demo-manager", at: "2026-11-01T09:00:00Z" }
          : null,
      },
      signing: { can_sign: false, reason: null, signer_id: "u-demo-director" },
    });
    state.documents.push(letter(1, "Письмо переданное", true), letter(2, "Письмо свежее", false));
    writeEds(state);

    await openDocuments("manager@demo.example", "?scope=mine");

    expect(
      await screen.findByRole("link", { name: "Открыть документ: Письмо переданное" }),
    ).toBeVisible();
    expect(within(row("Письмо переданное")).getByText("На подписи")).toBeVisible();
    expect(within(row("Письмо свежее")).getByText("Черновик")).toBeVisible();
    // ГЛ-0: у переданного письма в строке — у кого оно на подписи; у свежего подписанта нет
    expect(within(row("Письмо переданное")).getByText("у Демо Директоров")).toBeVisible();
    expect(within(row("Письмо свежее")).queryByText(/^у /)).toBeNull();
  });
});

describe("EDS · Документы: «Продолжить» только у своих", () => {
  it("в реестре у чужого черновика кнопки «Продолжить» нет", async () => {
    server.use(
      http.get("*/eds/documents", () =>
        HttpResponse.json({
          items: [
            {
              kind: "memo",
              id: "00000000-0000-4000-8000-0000000000c1",
              number: "СЗ-2026/040",
              subject: "Чужой черновик",
              status: "draft",
              author: { crm_user_id: 99, full_name: "Демо Другой" },
              amount: null,
              due_date: null,
              created_at: "2026-10-26T08:30:00Z",
              openable: true,
            },
          ],
          next_cursor: null,
        }),
      ),
    );
    await openDocuments("manager@demo.example", "?scope=all");

    await screen.findByRole("link", { name: "Открыть документ: Чужой черновик" });
    const tr = row("Чужой черновик");
    expect(within(tr).getByText("Черновик")).toBeVisible();
    expect(within(tr).queryByRole("link", { name: /Продолжить/ })).toBeNull();
  });
});

describe("EDS · Документы: карточка в боковом окне", () => {
  it("клик по документу: статус словами, реквизиты, текст, вложение, маршрут и решения с датой и автором", async () => {
    await openDocuments("manager@demo.example", "?scope=mine");

    fireEvent.click(
      await screen.findByRole("link", { name: "Открыть документ: Командировка в Самарканд" }),
    );

    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { level: 3, name: "Командировка в Самарканд" }),
    ).toBeVisible();
    expect(within(panel).getByText("СЗ-2026/028")).toBeVisible();
    expect(
      within(panel).getByText("Возвращена на доработку", { selector: ".ant-tag" }),
    ).toBeVisible();
    expect(within(panel).getByText("Директор")).toBeVisible();
    expect(within(panel).getByText("Директор — вернул на доработку")).toBeVisible();
    expect(within(panel).getByText(/Добавьте смету расходов/)).toBeVisible();
    expect(within(panel).getAllByText(/Демо Директоров/).length).toBeGreaterThan(0);
    expect(within(panel).getByRole("link", { name: "Продолжить" })).toHaveAttribute(
      "href",
      "/eds/new?draft=00000000-0000-4000-8000-000000000002",
    );
  });

  it("документ с суммой и вложением: маршрут автор → директор → бухгалтер, файл скачивается по кнопке", async () => {
    await openDocuments("manager@demo.example", "?scope=mine");

    fireEvent.click(
      await screen.findByRole("link", { name: "Открыть документ: Закупка канцтоваров на квартал" }),
    );

    const panel = await panelEl();
    expect(await within(panel).findByText("Директор — ждёт решения")).toBeVisible();
    expect(within(panel).getByText("Бухгалтер — дальше по маршруту")).toBeVisible();
    expect(within(panel).getByText("4 800 000 сум")).toBeVisible();
    expect(
      within(panel).getByRole("button", { name: "Скачать: schet-kanctovary.pdf" }),
    ).toBeVisible();
    expect(within(panel).queryByRole("link", { name: "Продолжить" })).toBeNull();
  });

  it("черновик без маршрута: подсказка, куда он пойдёт после отправки", async () => {
    await openDocuments("manager@demo.example", "?scope=mine");

    fireEvent.click(
      await screen.findByRole("link", {
        name: "Открыть документ: Ремонт кондиционера в переговорной",
      }),
    );

    const panel = await panelEl();
    expect(
      await within(panel).findByText(
        "Маршрут откроется после отправки: вы → директор → бухгалтер.",
      ),
    ).toBeVisible();
    expect(within(panel).getByText("Решений пока нет.")).toBeVisible();
  });

  it("чужой документ без доступа к реестру: «Документ не найден» словами", async () => {
    await openDocuments(
      "admin@demo.example",
      "?doc=00000000-0000-4000-8000-000000000006&panel=open",
    );

    const panel = await panelEl();
    expect(await within(panel).findByText("Документ не найден")).toBeVisible();
  });

  it("на телефоне список — карточками, а документ открывается листом на весь экран с кнопками внизу", async () => {
    setViewportWidth(390);
    await openDocuments("manager@demo.example", "?scope=mine");

    expect(screen.queryByRole("table")).toBeNull();
    const list = await screen.findByRole("list", { name: "Документы" });
    fireEvent.click(
      within(list).getByRole("link", { name: "Открыть документ: Командировка в Самарканд" }),
    );

    const sheet = await screen.findByRole("dialog", { name: "Документ" });
    expect(
      await within(sheet).findByRole("heading", { level: 3, name: "Командировка в Самарканд" }),
    ).toBeVisible();
    const actions = within(sheet).getByRole("link", { name: "Продолжить" })
      .parentElement as HTMLElement;
    expect(actions).toHaveAttribute("data-sheet", "true");
    fireEvent.click(within(actions).getByRole("button", { name: "Закрыть документ" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Документ" })).toBeNull();
    });
    cleanup();
  });
});

describe("«Исходящие» и «Архив» по стадии (план 2026-11-12 п. 0.9, FR-5)", () => {
  it("одобренное КП ждёт клиента — в «Исходящих» с суммой и «Открыть КП»; в «Архиве» его нет", async () => {
    signIn("director@demo.example");
    renderAt("/eds/documents?box=outgoing&scope=all");
    const row = (await screen.findByText("КП · Колёсные пары, 10 шт.")).closest("tr");
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);
    expect(cells.getByText("197 993 600 сум")).toBeInTheDocument();
    expect(
      cells.getByRole("link", { name: "Открыть КП: КП · Колёсные пары, 10 шт." }),
    ).toHaveAttribute("href", expect.stringMatching(/^\/eds\/drafts\//));
    cleanup();
    renderAt("/eds/documents?box=archive&scope=all");
    await listSettled();
    expect(screen.queryByText("КП · Колёсные пары, 10 шт.")).toBeNull();
  });

  it("архив: закрытое входящее письмо открывает само письмо — темой и ссылкой «Открыть письмо» (ДОК-8)", async () => {
    signIn("director@demo.example");
    renderAt("/eds/documents?box=archive&scope=all");
    await listSettled();
    const subject = "Изменение тарифов на расчётно-кассовое обслуживание с 1 декабря";
    const row = (await screen.findByText(subject)).closest("tr") as HTMLElement;
    const href = `/eds/inbox/${encodeURIComponent("ВХ-100/26")}`;
    // статус закрытого письма — словами, а не кодом
    expect(within(row).getByText("Принято к сведению")).toBeVisible();
    expect(within(row).getByRole("link", { name: `Открыть документ: ${subject}` })).toHaveAttribute(
      "href",
      href,
    );
    expect(within(row).getByRole("link", { name: `Открыть письмо: ${subject}` })).toHaveAttribute(
      "href",
      href,
    );
  });
});

describe("EDS · Документы: порядок по шапке (Х-15б)", () => {
  const stubRow = {
    kind: "memo",
    id: "00000000-0000-4000-8000-0000000000aa",
    number: "СЗ-2026/001",
    subject: "Первая страница",
    status: "approved",
    author: null,
    amount: null,
    due_date: null,
    created_at: "2026-11-01T10:00:00Z",
    openable: true,
    undelivered: false,
    awaiting_signature: false,
  };
  const spy = () => {
    const asked: { sort: string | null; cursor: string | null }[] = [];
    server.use(
      http.get("*/eds/documents", ({ request }) => {
        const params = new URL(request.url).searchParams;
        asked.push({ sort: params.get("sort"), cursor: params.get("cursor") });
        return HttpResponse.json({ items: [stubRow], next_cursor: "c1" });
      }),
    );
    return asked;
  };

  it("порядок из адреса уходит серверу вместе с курсором, чужое поле — нет", async () => {
    const asked = spy();
    await openDocuments("manager@demo.example", "?scope=mine&sort=-amount");
    await screen.findByRole("link", { name: "Открыть документ: Первая страница" });
    expect(asked[0]).toEqual({ sort: "-amount", cursor: null });

    cleanup();
    asked.length = 0;
    await openDocuments("manager@demo.example", "?scope=mine&sort=author_crm_user_id");
    await screen.findByRole("link", { name: "Открыть документ: Первая страница" });
    expect(asked[0]).toEqual({ sort: null, cursor: null });
  });

  it("смена порядка сбрасывает курсор: запрос идёт с первой страницы", async () => {
    const asked = spy();
    await openDocuments("manager@demo.example", "?scope=mine");
    await screen.findByRole("link", { name: "Открыть документ: Первая страница" });
    fireEvent.click(screen.getByRole("button", { name: "Дальше" }));
    await waitFor(() => {
      expect(asked.at(-1)).toEqual({ sort: null, cursor: "c1" });
    });

    fireEvent.click(screen.getByRole("button", { name: "Сумма" }));
    await waitFor(() => {
      expect(asked.at(-1)).toEqual({ sort: "amount", cursor: null });
    });
    expect(screen.getByText("Страница 1")).toBeVisible();
  });
});
