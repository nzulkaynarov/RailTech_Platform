import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { chooseOption } from "../../../test/fields";
import { resetMarks, setMark } from "../../../mocks/doNotWorkMarks";
import { clientStatusOf, readProjects, writeProject } from "../../../mocks/fixtures/projects";
import i18n from "../../../shared/i18n";
import ruProjects from "../../../shared/i18n/ru/projects.json";
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
  await waitFor(() => {
    if (
      within(panel).queryAllByText(name).length === 0 &&
      within(panel).queryAllByLabelText(name).length === 0
    )
      throw new Error(`нет кнопки «${name}»`);
  });
  fireEvent.click(within(panel).getByRole("button", { name }));
}

/** A2: «Согласован клиентом» — канал и лицо со стороны клиента, затем кнопка. */
async function agree(panel: HTMLElement, person = "Каримов А., снабженец") {
  await within(panel).findAllByText("Отметить: согласован клиентом");
  await chooseOption(within(panel).getByLabelText("Как клиент сообщил"), "почта");
  fireEvent.change(within(panel).getByLabelText("Кто со стороны клиента"), {
    target: { value: person },
  });
  fireEvent.click(within(panel).getByRole("button", { name: "Отметить: согласован клиентом" }));
}

function pick(input: HTMLElement, file: File) {
  fireEvent.change(input, { target: { files: [file] } });
}

/** Карточка проекта: действия по договору и акту — в строках документов в центре (ЕД-7), «panel» — область документов. */
async function openCard(user: string, n: number) {
  signIn(user);
  const view = renderAt(PR(n));
  const panel = await screen.findByRole("region", { name: "Документы проекта" });
  return { ...view, panel };
}

/** Вкладка бокового окна по имени: «Сведения», «История». */
async function sideTab(name: string): Promise<HTMLElement> {
  const side = await panelEl();
  const tab = await within(side).findByRole("tab", { name });
  fireEvent.click(tab);
  return side;
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
    expect(rows[1]).toHaveTextContent("Подписан");
    // события документов — только во вкладке «История», в строке их пересказа нет
    expect(rows[1]).not.toHaveTextContent("Демо Бухгалтеров");
    expect(docs).toHaveTextContent("СЧ-2026/131");
    expect(docs).toHaveTextContent("Оплачен");
    expect(docs).toHaveTextContent("АКТ-2026/051");
    expect(docs).toHaveTextContent("Выпущен");

    const execution = screen.getByRole("heading", { name: "Исполнение" }).closest(".ant-card");
    expect(execution).toHaveTextContent("Отгружено");
    expect(execution).toHaveTextContent("TRK-4471");
    expect(execution).not.toHaveTextContent("Склад · Отгрузки"); // без пересказа процесса (СЦ-8)
    // у бухгалтера раздел «Склад» только для чтения — отметок доставки нет (L0-1)
    expect(
      within(execution as HTMLElement).queryByRole("button", { name: "Доставлено" }),
    ).toBeNull();
    expect(screen.queryByRole("heading", { name: "Журнал документов" })).toBeNull();
  });

  it("каждое сведение — один раз: клиент и сумма только в «Сведениях», статус клиента — в шапке, № КП — в строке", async () => {
    signIn("accountant@demo.example");
    renderAt(PR(97));
    const docs = await screen.findByRole("region", { name: "Документы проекта" });
    const side = await sideTab("Сведения");
    const project = readProjects().find((p) => p.id === 97);
    if (!project) throw new Error("нет проекта 97");

    // клиент и менеджер — в «Сведениях» один раз и больше нигде на странице
    expect(within(side).getAllByText(project.client)).toHaveLength(1);
    expect(within(document.body).getAllByText(project.client)).toHaveLength(1);
    // статус для клиента — только тег шапки; в «Сведениях» его нет
    expect(within(side).queryByText("Клиент видит")).toBeNull();
    expect(screen.getAllByText(ruProjects.clientStatus[clientStatusOf(project)])).toHaveLength(1);
    // номер КП — только в строке документа
    expect(within(docs).getAllByText("КП-2026/110")).toHaveLength(1);
    expect(screen.getAllByText("КП-2026/110")).toHaveLength(1); // и нигде больше на странице
    expect(within(side).queryByText("Из КП")).toBeNull();
    // у договора и акта нет своей копии истории и шапки со статусом
    expect(screen.queryByRole("list", { name: "История договора" })).toBeNull();
    expect(screen.queryByRole("list", { name: "История акта" })).toBeNull();
    // колонки справа внутри страницы больше нет
    expect(document.querySelector(".pf-dec-side")).toBeNull();
  });

  it("СЦ-8: в шапке один статус — проблема, если она есть; без договора клиенту не предлагают его согласовать", async () => {
    signIn("director@demo.example");
    renderAt(PR(104));
    await screen.findByRole("region", { name: "Документы проекта" });
    // проекта договора нет: слово для клиента — «Готовим договор», но при проблеме в шапке только она
    expect(screen.getAllByText("Проекта договора нет")).toHaveLength(1);
    expect(screen.queryByText(ruProjects.clientStatus.contract_preparing)).toBeNull();
    expect(screen.queryByText(ruProjects.clientStatus.contract_review)).toBeNull();
  });

  it("СЦ-8: без проблем в шапке — слово для клиента по факту: договор отправлен — «Согласуйте редакцию»", async () => {
    signIn("director@demo.example");
    renderAt(PR(105));
    await screen.findByRole("region", { name: "Документы проекта" });
    expect(screen.getAllByText(ruProjects.clientStatus.contract_review)).toHaveLength(1);
  });

  it("СЦ-8: у проекта без договора в строке «Акт» — «Акта ещё нет.», без просьбы выставить счёт", async () => {
    signIn("director@demo.example");
    renderAt(PR(104));
    const docs = await screen.findByRole("region", { name: "Документы проекта" });
    expect(within(docs).getByText("Акта ещё нет.")).toBeVisible();
    expect(docs).not.toHaveTextContent("выставьте его");
  });

  it("«История»: журнал проекта один, договор/акт — фильтры; пустые вкладки не показываются", async () => {
    signIn("accountant@demo.example");
    renderAt(PR(97));
    await screen.findByRole("region", { name: "Документы проекта" });
    const side = await panelEl();
    // «Маршрут», «Обсуждение», «Документы» никто не наполняет — вкладок нет
    const names = (await within(side).findAllByRole("tab")).map((tab) => tab.textContent);
    expect(names).toEqual(["Сведения", "История"]);

    await sideTab("История");
    const list = within(side).getByRole("list", { name: "История проекта" });
    const all = within(list).getAllByRole("listitem");
    expect(all.length).toBeGreaterThan(1);
    fireEvent.click(within(side).getByRole("button", { name: "Акт" }));
    const onlyAct = within(
      within(side).getByRole("list", { name: "История проекта" }),
    ).getAllByRole("listitem");
    expect(onlyAct.length).toBeLessThan(all.length);
    onlyAct.forEach((li) => {
      expect(li).toHaveTextContent(/акт/i);
    });
  });

  it("менеджер читает карточку, но действий нет: пометка «Только чтение», в окне договора — пояснение", async () => {
    signIn("manager@demo.example");
    renderAt(PR(105));

    expect(await screen.findByText("Только чтение")).toBeVisible();
    const panel = await screen.findByRole("region", { name: "Документы проекта" });
    expect(await within(panel).findByText("ДОГ-2026/105", { exact: false })).toBeVisible();
    expect(
      within(panel).queryByRole("button", { name: /Отметить: согласован клиентом/ }),
    ).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Клиент отклонил договор…" })).toBeNull();
  });

  it("Х-8: у компании проекта «Не работать» — полоса с причиной, а договор в работе остаётся на месте", async () => {
    resetMarks();
    setMark("2001", "АО «Демо-Транс»", {
      reason: "Спор по оплате прошлой поставки",
      set_by: "Менеджер Демо",
      set_at: "2026-11-23T09:30:00Z",
      until: null,
    });
    signIn("director@demo.example");
    renderAt(PR(105));
    expect(
      await screen.findByText("С компанией не работаем: Спор по оплате прошлой поставки"),
    ).toBeVisible();
    expect(screen.getByText(/Отметил: Менеджер Демо/)).toBeVisible();
    const panel = await screen.findByRole("region", { name: "Документы проекта" });
    expect(await within(panel).findByText("ДОГ-2026/105", { exact: false })).toBeVisible();
    resetMarks();
  });

  it("без отметки полосы нет", async () => {
    resetMarks();
    signIn("director@demo.example");
    renderAt(PR(104));
    await screen.findByRole("region", { name: "Документы проекта" });
    expect(screen.queryByText(/С компанией не работаем/)).toBeNull();
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

describe("Проект: договор (строка документа)", () => {
  it("весь путь: формирование проекта → у контрагента → согласован → ожидает подписания → отметка заметкой → Подписан", async () => {
    // проект договора готов, визы бухгалтера и юриста собраны (Х-1) — его можно отправить клиенту
    const { panel } = await openCard("accountant@demo.example", 111);

    // проект не отправлен клиенту
    expect(await within(panel).findByText("Проект ещё не отправлен клиенту.")).toBeVisible();
    expect(within(panel).queryByTestId("contract-send-blocker")).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "На согласование клиенту" }));

    expect(await within(panel).findByText(/Договор у контрагента\./)).toBeVisible();
    await agree(panel);

    expect(
      await within(panel).findByText(/Редакция согласована\. Договор ожидает подписания/),
    ).toBeVisible();
    expect(within(panel).getAllByText("Ожидает подписания").length).toBeGreaterThan(0);
    // отметка: пока нет ни скана, ни заметки — кнопка неактивна
    const submit = within(panel).getByRole("button", { name: "Отметить: подписан" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(panel).getByLabelText("Или заметка"), {
      target: { value: "Подписан в офисе, оригинал у юриста" },
    });
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    fireEvent.click(submit);

    expect(await within(panel).findByText("Договор подписан.")).toBeVisible();
    expect(within(panel).getAllByText("Подписан").length).toBeGreaterThan(0);
    // история — одна, во вкладке «История»: кто и когда, записи по порядку (новые первыми)
    const side = await sideTab("История");
    const history = await within(side).findByRole("list", { name: "История проекта" });
    expect(within(history).getAllByRole("listitem")[0]).toHaveTextContent(
      "Договор отмечен подписанным",
    );
    expect(within(history).getAllByRole("listitem")[0]).toHaveTextContent("Демо Бухгалтеров");
    // СЦ-7: подпись записи — «Комментарий», а не «Причина»
    expect(
      within(history).getByText("Комментарий: Подписан в офисе, оригинал у юриста"),
    ).toBeVisible();
    expect(within(history).queryByText(/Причина: Подписан/)).toBeNull();
  });

  it("ДП-1: «Подписан» сканом вместо заметки — файл остаётся у договора", async () => {
    const { panel } = await openCard("accountant@demo.example", 111);
    await click(panel, "На согласование клиенту");
    await agree(panel);
    const submit = await within(panel).findByRole("button", { name: "Отметить: подписан" });
    pick(within(panel).getByLabelText("Скан подписанного договора"), PDF());
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    fireEvent.click(submit);

    expect(await within(panel).findByText("Договор подписан.")).toBeVisible();
    expect(within(panel).getByRole("button", { name: "Скан подписанного" })).toBeVisible();
  });

  it("Х-1: новый проект договора — «На согласование клиенту» не предлагается, причина словами; «На подпись» собирает визы", async () => {
    const { panel } = await openCard("accountant@demo.example", 104);
    fireEvent.click(
      await within(panel).findByRole("button", { name: "Сформировать проект договора по КП" }),
    );

    // договор не на визах: действия «На согласование клиенту» нет, причина — рядом
    const blocker = await within(panel).findByTestId("contract-send-blocker");
    expect(blocker).toHaveTextContent("Нужны визы. Нажмите «На подпись»");
    expect(within(panel).queryByRole("button", { name: "На согласование клиенту" })).toBeNull();
    expect(within(panel).queryByText("Только просмотр.")).toBeNull();

    // «На подпись» открывает круг виз: причина называет, чьих виз не хватает
    fireEvent.click(within(panel).getByRole("button", { name: "На подпись" }));
    await waitFor(() => {
      expect(within(panel).getByTestId("contract-send-blocker")).toHaveTextContent(
        "Нужны визы: бухгалтер, юрист",
      );
    });
    expect(within(panel).queryByRole("button", { name: "На согласование клиенту" })).toBeNull();
  });

  it("Х-1: визы возвращены — замечание визирующего в причине", async () => {
    const returned = readProjects().find((p) => p.id === 111);
    if (!returned?.contract) throw new Error("нет проекта 111");
    writeProject({ ...returned, contract: { ...returned.contract, visas: "returned" } });
    const { panel } = await openCard("accountant@demo.example", 111);
    const blocker = await within(panel).findByTestId("contract-send-blocker");
    expect(blocker).toHaveTextContent("Визы возвращены: бухгалтер");
    expect(blocker).toHaveTextContent("Замечание: Нет графика платежей");
    expect(within(panel).queryByRole("button", { name: "На согласование клиенту" })).toBeNull();
  });

  it("Х-1: некому визировать — администратору ссылка на «Сотрудники», без тупика", async () => {
    const found = readProjects().find((p) => p.id === 111);
    if (!found?.contract) throw new Error("нет проекта 111");
    writeProject({ ...found, contract: { ...found.contract, visas: "no_holder" } });
    const { panel } = await openCard("all@demo.example", 111);
    const noHolder = await within(panel).findByTestId("contract-send-blocker");
    expect(noHolder).toHaveTextContent("Некому поставить визу: юрист");
    expect(within(noHolder).getByRole("link", { name: "Сотрудники" })).toHaveAttribute(
      "href",
      "/admin/org",
    );
  });

  it("Х-1: некому визировать — тому, у кого нет доступа к «Сотрудникам», вместо ссылки слова, кого просить", async () => {
    const found = readProjects().find((p) => p.id === 111);
    if (!found?.contract) throw new Error("нет проекта 111");
    writeProject({ ...found, contract: { ...found.contract, visas: "no_holder" } });
    const { panel } = await openCard("accountant@demo.example", 111);
    const noHolder = await within(panel).findByTestId("contract-send-blocker");
    expect(noHolder).toHaveTextContent("Некому поставить визу: юрист");
    expect(within(noHolder).queryByRole("link")).toBeNull();
    expect(noHolder).toHaveTextContent("Попросите администратора назначить роль: юрист.");
  });

  it("Х-1: визы собираются — «На подпись» не предлагается (повтор отказал бы), причина по факту открытого запроса", async () => {
    const found = readProjects().find((p) => p.id === 111);
    if (!found?.contract) throw new Error("нет проекта 111");
    writeProject({ ...found, contract: { ...found.contract, visas: "pending" } });
    const { panel } = await openCard("accountant@demo.example", 111);
    expect(await within(panel).findByTestId("contract-send-blocker")).toHaveTextContent(
      "Нужны визы: бухгалтер, юрист",
    );
    expect(within(panel).queryByRole("button", { name: "На подпись" })).toBeNull();
  });

  it("Х-1: визы возвращены — запроса по текущей редакции нет, «На подпись» можно повторить", async () => {
    const found = readProjects().find((p) => p.id === 111);
    if (!found?.contract) throw new Error("нет проекта 111");
    writeProject({ ...found, contract: { ...found.contract, visas: "returned" } });
    const { panel } = await openCard("accountant@demo.example", 111);
    expect(await within(panel).findByRole("button", { name: "На подпись" })).toBeVisible();
  });

  it("Х-1: запрос открыт, а проекция виз ещё не пришла — «Визы собираются», без пустого хвоста", async () => {
    const found = readProjects().find((p) => p.id === 111);
    if (!found?.contract) throw new Error("нет проекта 111");
    writeProject({ ...found, contract: { ...found.contract, visas: "collecting" } });
    const { panel } = await openCard("accountant@demo.example", 111);
    const blocker = await within(panel).findByTestId("contract-send-blocker");
    expect(blocker).toHaveTextContent("Визы собираются.");
    expect(blocker).not.toHaveTextContent("Нужны визы:");
  });

  it("Х-1: роли виз названы на языке сотрудника, а не словами EDS", async () => {
    const found = readProjects().find((p) => p.id === 111);
    if (!found?.contract) throw new Error("нет проекта 111");
    writeProject({ ...found, contract: { ...found.contract, visas: "pending" } });
    const { panel } = await openCard("accountant@demo.example", 111);
    await within(panel).findByTestId("contract-send-blocker");
    try {
      await act(async () => {
        await i18n.changeLanguage("en");
      });
      const blocker = await within(panel).findByTestId("contract-send-blocker");
      expect(blocker).toHaveTextContent("Visas needed: accountant, lawyer");
      expect(blocker).not.toHaveTextContent("бухгалтер");
    } finally {
      await i18n.changeLanguage("ru");
    }
  });

  it("Х-1: визы собраны — действие есть, причины нет; сервер отказывает, если визы пропали (кто-то опередил)", async () => {
    const { panel } = await openCard("accountant@demo.example", 111);
    const button = await within(panel).findByRole("button", { name: "На согласование клиенту" });
    expect(within(panel).queryByTestId("contract-send-blocker")).toBeNull();

    // карточка устарела: за это время визу вернули — отказ словами, договор у клиента не появился
    const stale = readProjects().find((p) => p.id === 111);
    if (!stale?.contract) throw new Error("нет проекта 111");
    writeProject({ ...stale, contract: { ...stale.contract, visas: "pending" } });
    fireEvent.click(button);
    expect(await within(panel).findByText(/Сначала нужны визы/)).toBeVisible();
    expect(readProjects().find((p) => p.id === 111)?.contract?.sent_to_client).toBe(false);
  });

  it("A2: «Согласован клиентом» — без канала и лица не отмечается; в истории — «Отмечено сотрудником»", async () => {
    const { panel } = await openCard("accountant@demo.example", 111);
    await click(panel, "На согласование клиенту");
    await click(panel, "Отметить: согласован клиентом");

    expect(await within(panel).findByText("Укажите, как клиент сообщил")).toBeVisible();
    expect(within(panel).getByText("Укажите, кто подтвердил")).toBeVisible();
    expect(within(panel).getByText(/Договор у контрагента\./)).toBeVisible();

    await agree(panel, "Юсупова Н., юрист");
    expect(await within(panel).findByText(/Редакция согласована/)).toBeVisible();
    const side = await sideTab("История");
    const history = await within(side).findByRole("list", { name: "История проекта" });
    const last = within(history).getAllByRole("listitem")[0];
    expect(last).toHaveTextContent("Редакция договора согласована клиентом");
    expect(last).toHaveTextContent("Отмечено сотрудником");
    expect(last).toHaveTextContent("почта · подтвердил: Юсупова Н., юрист");
  });

  it("скан не того типа: кнопка остаётся неактивной, слово о типе; ошибка ERP показывается словами", async () => {
    const { panel } = await openCard("accountant@demo.example", 111);
    await click(panel, "На согласование клиенту");
    await agree(panel);
    const input = await within(panel).findByLabelText("Скан подписанного договора");

    pick(input, new File(["MZ"], "virus.exe", { type: "application/octet-stream" }));
    expect(
      await within(panel).findByText("Нужен PDF или изображение: JPG, PNG, WEBP."),
    ).toBeVisible();
    expect(within(panel).getByRole("button", { name: "Отметить: подписан" })).toBeDisabled();

    // правильное расширение, но не та сигнатура — отказ ERP словами
    // после выбора AntD Upload пересоздаёт поле файла: берём его заново
    pick(
      within(panel).getByLabelText("Скан подписанного договора"),
      new File(["not a pdf at all"], "fake.pdf", { type: "application/pdf" }),
    );
    await within(panel).findAllByText(/fake\.pdf/);
    expect(within(panel).getByRole("button", { name: "Отметить: подписан" })).toBeEnabled();
    fireEvent.click(within(panel).getByRole("button", { name: "Отметить: подписан" }));
    expect(await within(panel).findByText(/Файл не похож на скан/)).toBeVisible();
    expect(within(panel).getAllByText("Ожидает подписания").length).toBeGreaterThan(0);
  });

  it("отклонение клиентом: причина обязательна, потом «Вернуть в проект»", async () => {
    const { panel } = await openCard("accountant@demo.example", 105);
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
    // причина отказа — в «Истории», у договора её копии нет
    const side = await sideTab("История");
    expect(await within(side).findByText(/Срок оплаты 5 дней/)).toBeVisible();
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
    const { panel } = await openCard("accountant@demo.example", 105);
    await agree(panel);

    expect(
      await within(panel).findByText(
        "Не получилось: Договор уже в другом статусе. Обновите страницу.",
      ),
    ).toBeVisible();
    expect(within(panel).getByText(/Договор у контрагента\./)).toBeVisible();
  });
});

describe("Проект: договор — «Ожидает подписания» и замечания контрагента (ДП-1)", () => {
  const person = (id: number, name: string) => ({ id, name });
  const remark = (votes: { agree: boolean }[] = []) => ({
    id: 1,
    edition: 1,
    received_at: "2026-11-26T10:02:00+05:00",
    author_name: "Ш. Юсупов",
    comment: "Бюджет закрыт, 50 % сразу не проведём.",
    file_name: "редакция.docx",
    has_file: true,
    summary: { changed: ["2.2"], added: ["3.3"], removed: ["5.2"], total: 3, comparable: true },
    items: [
      {
        point: "2.2",
        kind: "changed" as const,
        ours: "Предоплата 50 %",
        theirs: "Предоплата 30 %",
        segments: [
          { op: "equal" as const, text: "Предоплата " },
          { op: "del" as const, text: "50" },
          { op: "ins" as const, text: "30" },
          { op: "equal" as const, text: " %" },
        ],
      },
    ],
    votes: votes.map((v, i) => ({
      user: person(10 + i, `Сотрудник ${String(i)}`),
      agree: v.agree,
      comment: v.agree ? "" : "Пеню оставляем",
      at: "2026-11-26T10:40:00+05:00",
    })),
    deciders: [person(3, "Д. Назаров")],
  });

  it("отметка «Подписан» заметкой без скана: срок и статус «Подписан», запись в истории", async () => {
    const project = readProjects().find((p) => p.id === 105);
    if (!project?.contract) throw new Error("fixture");
    writeProject({ ...project, contract: { ...project.contract, status: "client_agreed" } });
    const view = await openCard("accountant@demo.example", 105);
    expect(await within(view.panel).findByText("Ожидает подписания")).toBeVisible();
    const submit = within(view.panel).getByRole("button", { name: "Отметить: подписан" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(view.panel).getByLabelText("Или заметка"), {
      target: { value: "Подписан в офисе, оригинал у юриста" },
    });
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    fireEvent.click(submit);
    expect(await within(view.panel).findByText("Договор подписан.")).toBeVisible();
    expect(readProjects().find((p) => p.id === 105)?.contract?.status).toBe("signed");
  });

  it("замечания: разбор и сравнение видны, «Не согласен» без слов не уходит; все согласны — «Ожидает подписания»", async () => {
    const project = readProjects().find((p) => p.id === 105);
    if (!project?.contract) throw new Error("fixture");
    writeProject({
      ...project,
      contract: { ...project.contract, remark: remark(), remark_awaiting: [person(1, "Вы")] },
    });
    const { panel } = await openCard("accountant@demo.example", 105);
    const block = await within(panel).findByTestId("contract-remark");
    expect(within(block).getByText("Бюджет закрыт, 50 % сразу не проведём.")).toBeVisible();
    expect(within(block).getByTestId("remark-summary")).toHaveTextContent(
      "Изменены п. 2.2; Добавлены п. 3.3; Удалены п. 5.2",
    );
    expect(within(block).getByText("50").tagName).toBe("DEL");
    expect(within(block).getByText("30").tagName).toBe("INS");
    // решающий голос закрывает замечания, не дожидаясь тех, кто не ответил
    expect(
      within(block).getByRole("button", { name: "Принять редакцию контрагента" }),
    ).toBeVisible();
    // основная кнопка «согласован клиентом» при замечаниях не предлагается
    expect(
      within(panel).queryByRole("button", { name: "Отметить: согласован клиентом" }),
    ).toBeNull();

    fireEvent.click(within(block).getByRole("button", { name: "Не согласен" }));
    expect(await within(block).findByText("Напишите, с чем не согласны.")).toBeVisible();
    fireEvent.click(within(block).getByRole("button", { name: "Согласен" }));
    expect(await within(panel).findByText(/Редакция согласована/)).toBeVisible();
    expect(readProjects().find((p) => p.id === 105)?.contract?.status).toBe("client_agreed");
  });

  it("решающего голоса нет ни у кого: сказано, где его выдать, а не пустое «решает: »", async () => {
    const project = readProjects().find((p) => p.id === 105);
    if (!project?.contract) throw new Error("fixture");
    writeProject({
      ...project,
      contract: { ...project.contract, remark: { ...remark(), deciders: [] }, remark_awaiting: [] },
    });
    const { panel } = await openCard("director@demo.example", 105);
    const block = await within(panel).findByTestId("contract-remark");
    expect(within(block).queryByTestId("remark-deciders")).toBeNull();
    expect(within(block).getByTestId("remark-no-decider")).toHaveTextContent(
      "Решающий голос не назначен",
    );
    expect(
      within(block).queryByRole("button", { name: "Принять редакцию контрагента" }),
    ).toBeNull();
  });

  it("разногласие: решение за директором — принять редакцию контрагента или ответить своей", async () => {
    const project = readProjects().find((p) => p.id === 105);
    if (!project?.contract) throw new Error("fixture");
    writeProject({
      ...project,
      contract: { ...project.contract, remark: remark([{ agree: true }, { agree: false }]) },
    });
    const { panel } = await openCard("director@demo.example", 105);
    const block = await within(panel).findByTestId("contract-remark");
    expect(within(block).getByText("Решающий голос: Д. Назаров")).toBeVisible();
    fireEvent.click(within(block).getByRole("button", { name: "Ответить своей редакцией" }));
    const send = within(block).getByRole("button", { name: "Отправить ответ" });
    expect(send).toBeDisabled();
    fireEvent.change(within(block).getByLabelText("Что отвечаем контрагенту"), {
      target: { value: "Предоплата 40 %" },
    });
    fireEvent.click(send);
    await waitFor(() => {
      expect(readProjects().find((p) => p.id === 105)?.contract?.remark).toBeUndefined();
    });
    expect(readProjects().find((p) => p.id === 105)?.contract?.status).toBe("project");
  });
});

describe("Проект: акт (строка документа)", () => {
  it("скан подписанного акта → «Подписан (скан)», проект «Выполнено»", async () => {
    const { panel } = await openCard("accountant@demo.example", 97);

    expect(await within(panel).findByText(/Акт у клиента на приёмке/)).toBeVisible();
    const submit = within(panel).getByRole("button", { name: "Прикрепить скан" });
    expect(submit).toBeDisabled();
    pick(within(panel).getByLabelText("Скан подписанного акта"), PDF());
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    fireEvent.click(submit);

    expect(await within(panel).findByText("Акт подписан, скан сохранён.")).toBeVisible();
    // проект закрыт: шаг «Выполнено», статус для клиента «Выполнено», запись в журнале
    expect(
      await screen.findByText("Проект выполнен: акт принят, все счета оплачены."),
    ).toBeVisible();
    const side = await sideTab("История");
    expect(await within(side).findByText("Проект выполнен")).toBeVisible();
  });

  it("принят клиентом в кабинете, файла нет → «Принят клиентом», слова «скан» нет (СЦ-8)", async () => {
    const { panel } = await openCard("accountant@demo.example", 72);

    expect(
      await within(panel).findByText("Клиент принял акт в кабинете. Скана нет."),
    ).toBeVisible();
    const detail = within(panel)
      .getByText("Клиент принял акт в кабинете. Скана нет.")
      .closest("li") as HTMLElement;
    expect(within(detail).getByText("Принят")).toBeVisible(); // поле даты
    expect(detail).not.toHaveTextContent("Подписан (скан)");
    expect(detail).not.toHaveTextContent("скан сохранён");
    const docs = screen.getByRole("region", { name: "Документы проекта" });
    expect(docs).toHaveTextContent("АКТ-2026/044");
    const actRow = within(docs).getByText("АКТ-2026/044").closest("li") as HTMLElement;
    expect(actRow).toHaveTextContent("Принят клиентом");
    expect(actRow).not.toHaveTextContent("скан");
  });

  it("возврат заказчиком с причиной → «Возвращён с причиной» → выпустить заново", async () => {
    const { panel } = await openCard("accountant@demo.example", 97);
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
    const { panel } = await openCard("accountant@demo.example", 105);
    // факт — `act_blocker = no_invoice`: подпись называет причину и следующий шаг, а не общую фразу
    expect(await within(panel).findByText(/Счёт пока не выставлен — выставьте его/)).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Выпустить акт по проекту" })).toBeNull();
  });

  it("счёт есть, товар не доставлен: вместо кнопки — «после доставки»; доставлен — кнопка есть (СЦ-9)", async () => {
    const project = readProjects().find((p) => p.id === 97);
    if (!project) throw new Error("нет проекта 97");
    writeProject({ ...project, act: null });
    const { panel } = await openCard("accountant@demo.example", 97);
    expect(await within(panel).findByText(/Акт — после доставки/)).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Выпустить акт по проекту" })).toBeNull();
  });

  it("доставлено: акт можно выпустить", async () => {
    const project = readProjects().find((p) => p.id === 97);
    if (!project?.fulfillment) throw new Error("нет исполнения проекта 97");
    writeProject({
      ...project,
      act: null,
      fulfillment: { ...project.fulfillment, status: "DELIVERED", status_name: "Доставлено" },
    });
    const { panel } = await openCard("accountant@demo.example", 97);
    expect(
      await within(panel).findByRole("button", { name: "Выпустить акт по проекту" }),
    ).toBeVisible();
  });
});
