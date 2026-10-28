import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";

import { panelEl, renderAt, setupProjectTests, signIn } from "../../../test/projectsKit";

setupProjectTests();

const PR = (n: number) =>
  `/eds/projects/${encodeURIComponent(`ПР-2026-${String(n).padStart(3, "0")}`)}`;
const PDF = () => new File(["%PDF-1.4 demo scan"], "scan.pdf", { type: "application/pdf" });

/**
 * Кнопка появляется после ответа мока. Ждём её дешёвым запросом по тексту, а не `findByRole`: запрос по роли в цикле
 * ожидания считает доступность каждого узла антовской разметки и занимает поток, пока React не успевает отрисовать ответ.
 */
async function click(panel: HTMLElement, name: string) {
  await within(panel).findAllByText(name);
  fireEvent.click(within(panel).getByRole("button", { name }));
}

function pick(input: HTMLElement, file: File) {
  fireEvent.change(input, { target: { files: [file] } });
}

async function openTab(user: string, n: number, tab: "contract" | "act") {
  signIn(user);
  const view = renderAt(`${PR(n)}?panel=open&tab=${tab}`);
  const panel = await panelEl();
  return { ...view, panel };
}

describe("Проект: карточка", () => {
  it("шапка, шкала пути, документы КП · Договор · Счёт · Акт с историей, исполнение, журнал", async () => {
    signIn("accountant@demo.example");
    renderAt(PR(97));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Проект ПР-2026-097" }),
    ).toBeVisible();
    const steps = screen.getByRole("list", { name: /Путь заявки/ });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(7);
    expect(within(steps).getByText("Оплата").closest("li")).toHaveAttribute("aria-current", "step");

    const docs = screen.getByRole("region", { name: "Документы проекта" });
    const rows = within(docs).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("КП-2026/110");
    expect(rows[0]).toHaveTextContent("Принято клиентом");
    expect(rows[1]).toHaveTextContent("ДОГ-2026/097");
    expect(rows[1]).toHaveTextContent("Подписан (скан)");
    expect(rows[1]).toHaveTextContent("Демо Бухгалтеров"); // история: кто и когда
    expect(docs).toHaveTextContent("СЧ-2026/131");
    expect(docs).toHaveTextContent("Оплачен");
    expect(docs).toHaveTextContent("АКТ-2026/051");
    expect(docs).toHaveTextContent("Выпущен");

    const execution = screen.getByRole("heading", { name: "Исполнение" }).closest(".ant-card");
    expect(execution).toHaveTextContent("Доставлено");
    expect(execution).toHaveTextContent("TRK-4471");
    expect(execution).toHaveTextContent("Данные из ERP — только чтение");
    expect(screen.getByRole("heading", { name: "Журнал документов" })).toBeVisible();
  });

  it("менеджер читает карточку, но действий нет: пометка «Только чтение», в окне договора — пояснение", async () => {
    signIn("manager@demo.example");
    renderAt(`${PR(105)}?panel=open&tab=contract`);

    expect(await screen.findByText("Только чтение")).toBeVisible();
    const panel = await panelEl();
    expect(await within(panel).findByText("ДОГ-2026/105", { exact: false })).toBeVisible();
    expect(
      within(panel).queryByRole("button", { name: /Отметить: согласован клиентом/ }),
    ).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Клиент отклонил договор…" })).toBeNull();
    expect(
      within(panel).getByText(/Действия по договору доступны директору и бухгалтеру/),
    ).toBeVisible();
  });

  it("проекта нет — «Проект не найден» со ссылкой на список", async () => {
    signIn("director@demo.example");
    renderAt(PR(999));
    expect(await screen.findByText("Проект не найден")).toBeVisible();
    expect(screen.getByRole("link", { name: "К списку проектов" })).toBeVisible();
  });

  it("номер с чужим годом — тоже «не найден»", async () => {
    signIn("director@demo.example");
    renderAt(`/eds/projects/${encodeURIComponent("ПР-2025-104")}`);
    expect(await screen.findByText("Проект не найден")).toBeVisible();
  });
});

describe("Проект: договор (вкладка в боковом окне)", () => {
  it("весь путь: формирование проекта → на согласование клиенту → согласован → выставлен у оператора → скан → Подписан", async () => {
    const { panel } = await openTab("accountant@demo.example", 104, "contract");

    // договора нет: бухгалтер формирует проект
    expect(await within(panel).findByText("Договора ещё нет")).toBeVisible();
    const consequence = within(panel).getByRole("group", { name: "Что произойдёт" });
    expect(within(consequence).getAllByRole("listitem")).toHaveLength(3);
    fireEvent.click(within(panel).getByRole("button", { name: "Сформировать проект договора" }));

    // проект не отправлен клиенту
    expect(await within(panel).findByText("Проект ещё не отправлен клиенту.")).toBeVisible();
    expect(within(panel).getByText("не отправлен")).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "На согласование клиенту" }));

    expect(
      await within(panel).findByText("Проект у клиента на согласовании редакции."),
    ).toBeVisible();
    await click(panel, "Отметить: согласован клиентом");

    expect(await within(panel).findByText(/Клиент согласовал редакцию/)).toBeVisible();
    fireEvent.change(within(panel).getByLabelText(/Оператор или номер/), {
      target: { value: "Didox, № 77" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Отметить: выставлен у оператора" }));

    expect(
      await within(panel).findByText(/Договор выставлен у оператора\. Когда обе стороны/),
    ).toBeVisible();
    expect(within(panel).getAllByText("Выставлен у оператора").length).toBeGreaterThan(0);
    expect(within(panel).getByText(/Didox, № 77/)).toBeVisible();

    // скан: пока файла нет — кнопка неактивна, подпись говорит почему
    const submit = within(panel).getByRole("button", { name: "Прикрепить скан → Подписан" });
    expect(submit).toBeDisabled();
    expect(within(panel).getByText("Выберите файл скана — кнопка станет доступной.")).toBeVisible();
    pick(within(panel).getByLabelText("Скан подписанного договора"), PDF());
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    fireEvent.click(submit);

    expect(
      await within(panel).findByText("Договор подписан обеими сторонами, скан сохранён."),
    ).toBeVisible();
    expect(within(panel).getByText("Подписан (скан)")).toBeVisible();
    expect(within(panel).getByRole("button", { name: "Скан подписанного" })).toBeVisible();
    // история договора: кто и когда, записи по порядку (новые первыми)
    const history = within(panel).getByRole("list", { name: "История договора" });
    expect(within(history).getAllByRole("listitem")[0]).toHaveTextContent(
      "Прикреплён скан подписанного договора",
    );
    expect(within(history).getAllByRole("listitem")[0]).toHaveTextContent("Демо Бухгалтеров");
  });

  it("скан не того типа: кнопка остаётся неактивной, слово о типе; ошибка ERP показывается словами", async () => {
    const { panel } = await openTab("accountant@demo.example", 104, "contract");
    await click(panel, "Сформировать проект договора");
    await click(panel, "На согласование клиенту");
    await click(panel, "Отметить: согласован клиентом");
    await click(panel, "Отметить: выставлен у оператора");
    const input = await within(panel).findByLabelText("Скан подписанного договора");

    pick(input, new File(["MZ"], "virus.exe", { type: "application/octet-stream" }));
    expect(
      await within(panel).findByText("Нужен PDF или изображение: JPG, PNG, WEBP."),
    ).toBeVisible();
    expect(
      within(panel).getByRole("button", { name: "Прикрепить скан → Подписан" }),
    ).toBeDisabled();

    // правильное расширение, но не та сигнатура — отказ ERP словами
    pick(input, new File(["not a pdf at all"], "fake.pdf", { type: "application/pdf" }));
    await waitFor(() => {
      expect(
        within(panel).getByRole("button", { name: "Прикрепить скан → Подписан" }),
      ).toBeEnabled();
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Прикрепить скан → Подписан" }));
    expect(await within(panel).findByText(/Файл не похож на скан/)).toBeVisible();
    expect(within(panel).getAllByText("Выставлен у оператора").length).toBeGreaterThan(0);
  });

  it("отклонение клиентом: причина обязательна, потом «Вернуть в проект»", async () => {
    const { panel } = await openTab("accountant@demo.example", 105, "contract");
    await click(panel, "Клиент отклонил договор…");

    const form = within(panel).getByRole("form", { name: "Клиент отклонил договор" });
    const submit = within(form).getByRole("button", { name: "Записать отклонение" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAccessibleDescription(
      "Кнопка станет доступной, когда вы напишете причину.",
    );
    fireEvent.change(within(form).getByLabelText("Причина отклонения"), {
      target: { value: "  " },
    });
    expect(submit).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Причина отклонения"), {
      target: { value: "Срок оплаты 5 дней" },
    });
    fireEvent.click(submit);

    expect(
      await within(panel).findByText(/Клиент отклонил договор\. Исправьте проект/),
    ).toBeVisible();
    expect(within(panel).getByText(/Срок оплаты 5 дней/)).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Вернуть в проект" }));
    expect(await within(panel).findByText("Проект ещё не отправлен клиенту.")).toBeVisible();
  });

  it("недопустимый переход (кто-то опередил): слова вместо кода, карточка остаётся", async () => {
    server.use(
      http.post("*/eds/projects/:ref/contract", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "Объект изменился. Обновите страницу.",
            source: "erp",
            details: { backend_status: 409, reason: "contract_transition_not_allowed" },
          },
          { status: 409 },
        ),
      ),
    );
    const { panel } = await openTab("accountant@demo.example", 105, "contract");
    await click(panel, "Отметить: согласован клиентом");

    expect(
      await within(panel).findByText(
        "Не получилось: Договор уже в другом статусе. Обновите страницу.",
      ),
    ).toBeVisible();
    expect(within(panel).getByText("Проект у клиента на согласовании редакции.")).toBeVisible();
  });
});

describe("Проект: акт (вкладка в боковом окне)", () => {
  it("скан подписанного акта → «Подписан (скан)», проект «Выполнено»", async () => {
    const { panel } = await openTab("accountant@demo.example", 97, "act");

    expect(await within(panel).findByText(/Акт у клиента на приёмке/)).toBeVisible();
    const submit = within(panel).getByRole("button", { name: "Прикрепить скан → Подписан" });
    expect(submit).toBeDisabled();
    pick(within(panel).getByLabelText("Скан подписанного акта"), PDF());
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    fireEvent.click(submit);

    expect(await within(panel).findByText("Акт подписан, скан сохранён.")).toBeVisible();
    // проект закрыт: шаг «Выполнено», статус для клиента «Выполнено», запись в журнале
    expect(
      await screen.findByText("Проект выполнен: акт подписан, все счета оплачены."),
    ).toBeVisible();
    expect(screen.getAllByText("Проект выполнен").length).toBeGreaterThan(0);
  });

  it("возврат заказчиком с причиной → «Возвращён с причиной» → выпустить заново", async () => {
    const { panel } = await openTab("accountant@demo.example", 97, "act");
    await click(panel, "Заказчик вернул акт…");
    const form = within(panel).getByRole("form", { name: "Заказчик вернул акт" });
    const submit = within(form).getByRole("button", { name: "Записать возврат" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Причина возврата"), {
      target: { value: "Опечатка в сумме" },
    });
    fireEvent.click(submit);

    expect(await within(panel).findByText(/Клиент вернул акт с причиной/)).toBeVisible();
    expect(within(panel).getByText("Причина возврата: Опечатка в сумме")).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Выпустить заново" }));
    expect(await within(panel).findByText(/Акт у клиента на приёмке/)).toBeVisible();
  });

  it("акта нет и счёта нет: подпись объясняет, когда его можно выпустить", async () => {
    const { panel } = await openTab("accountant@demo.example", 105, "act");
    expect(await within(panel).findByText("Акта ещё нет")).toBeVisible();
    expect(within(panel).getByText(/Акт выпускается по выставленному счёту/)).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Выпустить акт" })).toBeNull();
  });
});
