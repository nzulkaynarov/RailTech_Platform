import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HttpResponse, http } from "msw";

import { companyToday } from "../../../shared/lib/dates";
import {
  addCompany,
  chooseOption,
  fillDate,
  pickCompany,
  selectedLabel,
} from "../../../test/fields";
import { server } from "../../../test/server";
import { readEds, writeEds } from "../../../mocks/fixtures/edsDocuments";
import { readLetters, writeLetters } from "../../../mocks/fixtures/letters";
import { renderAt, setupEdsTests, signIn } from "../../../test/edsKit";

// pdf.js в jsdom не рисует: просмотр страниц проверяют e2e, здесь — состояния блока PDF.
vi.mock("../../../shared/ui/PdfViewer", () => ({
  default: ({ name }: { name: string }) => <div data-testid="pdf-pages">{name}</div>,
}));

// Редактор письма в jsdom не принимает ввод (contenteditable): здесь — поле текста с тем же id и подписью; сам редактор
// проверяют BodyEditor.test и e2e в браузере.
vi.mock("../../../shared/ui/BodyEditor/BodyEditor", async () => {
  const { paragraphOf } = await import("../../../shared/ui/BodyEditor/bodyModel");
  return {
    BodyEditor: ({
      id,
      label,
      value,
      revision = 0,
      onChange,
      invalid,
      describedBy,
    }: {
      id: string;
      label: string;
      value: { content?: { content?: { text?: string }[] }[] };
      revision?: number;
      onChange: (doc: unknown) => void;
      invalid?: boolean;
      describedBy?: string;
    }) => (
      // Замена тела снаружи (помощник письма, план 1.4) — как у редактора: поле берёт `value` при смене revision
      <textarea
        key={revision}
        defaultValue={(value.content ?? [])
          .map((block) => (block.content ?? []).map((node) => node.text ?? "").join(""))
          .join("\n\n")}
        id={id}
        aria-label={label}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onChange={(event) => {
          onChange({ type: "doc", content: event.target.value.split("\n\n").map(paragraphOf) });
        }}
      />
    ),
  };
});

setupEdsTests();

async function openForm(email: string, search = "") {
  signIn(email);
  const view = renderAt(`/eds/new${search}`);
  expect(
    await screen.findByRole("heading", {
      level: 1,
      name: /^(Внутренний документ|Исходящее письмо|Новый документ)$/,
    }),
  ).toBeVisible();
  return view;
}

function type(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** Адресат письма — только из контрагентов (СУЩ-2.6): поиск и выбор подсказки. */
async function pickAddressee(query = "демо", name = "АО «Демо-Путь»") {
  await pickCompany(screen.getByLabelText("Адресат (организация)"), query, name);
}

/** Открыть секцию формы (секции по шагам, platform-frontend.md §4.1a) щелчком по её заголовку. */
function step(title: RegExp) {
  fireEvent.click(screen.getByRole("button", { name: title, expanded: false }));
}

/** Нажать кнопку шага «Проверка и отправка». */
async function press(name: string) {
  const head = screen.queryByRole("button", { name: /Проверка и отправка/, expanded: false });
  if (head) fireEvent.click(head);
  // Значок загрузки уходит с анимацией, которой в jsdom нет: имя кнопки на миг содержит «loading».
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(`${name}$`) }));
}

/** Служебка с суммой без счёта: «Счёт партнёра придёт позже» (Б-9). */
function invoiceLater() {
  const head = screen.queryByRole("button", { name: /Текст и вложения/, expanded: false });
  if (head) fireEvent.click(head);
  fireEvent.click(screen.getByRole("checkbox", { name: "Счёт партнёра придёт позже" }));
}

function fillMemo(subject = "Закупка канцтоваров", text = "Прошу согласовать закупку.") {
  type("Тема", subject);
  type("Текст", text);
}

describe("EDS · Создать документ: форма", () => {
  it("служебная записка по умолчанию: тема, кому (директор), текст, сумма, срок, вложения, главная и вторичная кнопки", async () => {
    await openForm("manager@demo.example");

    // шаг 1 «О чём» открыт: тип, тема, кому, сумма, срок, связь с проектом
    expect(screen.getByLabelText("Тип документа")).toBeInTheDocument();
    expect(screen.getByLabelText("Тема")).toBeVisible();
    expect(screen.getByLabelText("Кому")).toHaveValue("На согласование");
    expect(screen.getByLabelText("Кому")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Сумма, сум")).toBeVisible();
    expect(screen.getByLabelText("Нужно до")).toBeVisible();
    // менеджеру открыты заявки: поле «Связь с проектом» есть
    expect(screen.getByLabelText("Связь с проектом")).toBeInTheDocument();
    // черновик сохраняется, когда есть тема и текст: пока их нет — подсказка вместо кнопки
    expect(screen.queryByRole("button", { name: "Сохранить черновик" })).toBeNull();
    // подсказка — в подвале каждого шага; открыт первый
    expect(screen.getAllByText("Черновик сохраняется, когда есть тема и текст.")[0]).toBeVisible();
    fillMemo();
    expect(screen.getByRole("button", { name: "Сохранить черновик" })).toBeVisible();
    // шаг 2 «Текст и вложения»
    step(/Текст и вложения/);
    expect(screen.getByLabelText("Текст")).toBeVisible();
    expect(screen.getByLabelText("Вложения")).toBeVisible();
    expect(screen.getByLabelText("Тема")).not.toBeVisible();
    // шаг 4 «Проверка и отправка»: главная кнопка — в конце
    step(/Проверка и отправка/);
    expect(screen.getByRole("button", { name: "Отправить на согласование" })).toBeVisible();
  });

  it("адресат письма — выбор из контрагентов: компания даёт ИНН и почту, человек из её карточки — «Кому» и свою почту; сбросить — снять", async () => {
    await openForm("director@demo.example", "?type=letter");
    expect(screen.getByLabelText("Кому — человек")).toBeDisabled();
    // строка «Кому» на бланке — одна, подписана как строка адресата; прежнего «Кому (должность и ФИО)» рядом нет
    expect(screen.getByLabelText("Строка адресата")).toBeInTheDocument();
    expect(screen.queryByLabelText("Кому (должность и ФИО)")).toBeNull();
    await pickAddressee();
    expect(selectedLabel(screen.getByLabelText("Адресат (организация)"))).toBe("АО «Демо-Путь»");
    expect(screen.getByText("ИНН 300000777")).toBeVisible();
    expect(screen.getByLabelText("Почта адресата")).toHaveValue("office@demo-put.example");
    // человек: люди компании из её карточки; выбор подставляет должность, имя и его почту
    await chooseOption(screen.getByLabelText("Кому — человек"), "Демо Клиентов");
    expect(screen.getByLabelText("Строка адресата")).toHaveValue("Главный инженер Демо Клиентов");
    expect(screen.getByLabelText("Почта адресата")).toHaveValue("d.klientov@demo-put.example");
    // свободного текста нет: поле даёт только выбор, очистка снимает компанию и выключает «человека»
    const clear = screen
      .getByLabelText("Адресат (организация)")
      .closest(".ant-select")
      ?.querySelector(".ant-select-clear");
    fireEvent.mouseDown(clear as Element);
    fireEvent.click(clear as Element);
    expect(selectedLabel(screen.getByLabelText("Адресат (организация)"))).toBe("");
    expect(screen.getByLabelText("Кому — человек")).toBeDisabled();
  });

  it("смена компании и снятие человека не оставляют в письме почту и «Кому» прежнего человека", async () => {
    await openForm("director@demo.example", "?type=letter");
    await pickAddressee();
    const person = screen.getByLabelText("Кому — человек");
    await chooseOption(person, "Демо Клиентов");
    expect(screen.getByLabelText("Почта адресата")).toHaveValue("d.klientov@demo-put.example");
    // человека сняли: возвращается общая почта компании, «Кому» от человека уходит
    const clearPerson = person.closest(".ant-select")?.querySelector(".ant-select-clear");
    fireEvent.mouseDown(clearPerson as Element);
    fireEvent.click(clearPerson as Element);
    expect(screen.getByLabelText("Почта адресата")).toHaveValue("office@demo-put.example");
    expect(screen.getByLabelText("Строка адресата")).toHaveValue("");
    // компания A -> человек -> компания B без почты: ничего от A
    await chooseOption(screen.getByLabelText("Кому — человек"), "Демо Клиентов");
    await pickAddressee("гни", "ГНИ Мирабадского района");
    expect(screen.getByLabelText("Почта адресата")).toHaveValue("");
    expect(screen.getByLabelText("Строка адресата")).toHaveValue("");
    // «Кому», которое вписал сам сотрудник, смена компании не трогает
    fireEvent.change(screen.getByLabelText("Строка адресата"), {
      target: { value: "Начальнику отдела" },
    });
    await pickAddressee("демо", "АО «Демо-Путь»");
    expect(screen.getByLabelText("Строка адресата")).toHaveValue("Начальнику отдела");
  });

  it("адресата нет среди контрагентов: «Завести» последней строкой — и она становится адресатом; тот же ИНН — предлагается существующая (ЕД-6)", async () => {
    await openForm("director@demo.example", "?type=letter");
    const field = screen.getByLabelText("Адресат (организация)");
    await addCompany(field, "Таможенный комитет", "200000123");
    expect(selectedLabel(field)).toBe("Таможенный комитет");
    expect(screen.getByText("ИНН 200000123")).toBeVisible();
    // дубль по ИНН: вторая компания не заводится, выбирается найденная
    await addCompany(field, "Таможня-2", "300000777");
    expect(selectedLabel(field)).toBe("АО «Демо-Путь»");
  });

  it("?type=letter у роли с доступом к входящим: письмо на бланке — адресат, почта, «кому», блоки, подписант; без суммы и срока", async () => {
    await openForm("director@demo.example", "?type=letter");

    expect(screen.getByLabelText("Адресат (организация)")).toBeVisible();
    expect(screen.getByLabelText("Почта адресата")).toBeVisible();
    expect(screen.getByLabelText("Строка адресата")).toBeVisible();
    expect(screen.queryByLabelText("Кому")).toBeNull();
    expect(screen.queryByLabelText("Сумма, сум")).toBeNull();
    expect(screen.queryByLabelText("Нужно до")).toBeNull();
    step(/Текст и вложения/);
    expect(screen.getByLabelText("Текст")).toBeVisible();
    // подписант по умолчанию — из бланка компании (шаг «Согласование и подпись»)
    step(/Согласование и подпись/);
    expect(
      await screen.findByText("Пусто — подписант бланка: Каримов А. А., Директор."),
    ).toBeVisible();
    step(/Проверка и отправка/);
    // СЦ-9: письмо на бланке не регистрируется без подписи — последний шаг «Передать на подпись» и у директора
    expect(screen.getByRole("button", { name: "Передать на подпись" })).toBeVisible();
    type("Почта адресата", "gni@example.uz");
    expect(screen.getByRole("button", { name: "Передать на подпись" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Зарегистрировать/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отправить на согласование" })).toBeNull();
    expect(screen.getByRole("region", { name: "PDF на бланке" })).toBeVisible();
  });

  it("ЕД-6: подписант письма — выбор из держателей права подписи, должность из справочника правится для «и. о.»", async () => {
    await openForm("manager@demo.example", "?type=letter");
    step(/Согласование и подпись/);

    // текстом имя подписанта не вписывается: поле — выбор
    const signer = await screen.findByRole("combobox", { name: "Подписант" });
    expect(screen.queryByRole("textbox", { name: "Подписант" })).toBeNull();
    fireEvent.mouseDown(signer);
    fireEvent.click(await screen.findByTitle("Демо Директоров"));

    const position = screen.getByLabelText("Должность подписанта");
    expect(position).toHaveAttribute("placeholder", "Директор");
    expect(position).toHaveValue("");
    fireEvent.change(position, { target: { value: "И. о. директора" } });
    expect(position).toHaveValue("И. о. директора");
  });

  it("ЕД-6: у сохранённого подписанта пропало право — в поле имя, а не id", async () => {
    const state = readEds();
    const draft = state.documents.find((d) => d.id === "00000000-0000-4000-8000-000000000004");
    if (!draft) throw new Error("fixture draft is missing");
    draft.kind = "letter_out";
    draft.letter = {
      body: null,
      recipient_attention: null,
      recipient_email: null,
      signatory_name: "Бывший Подписантов",
      signatory_position: null,
      signer_crm_user_id: 999,
      pdf: null,
      pdfPolls: 0,
      mailings: [],
      registration_requested: null,
    };
    writeEds(state);
    await openForm("manager@demo.example", "?draft=00000000-0000-4000-8000-000000000004");
    await screen.findByDisplayValue("Ремонт кондиционера в переговорной");
    step(/Согласование и подпись/);

    expect(await screen.findByText("Бывший Подписантов")).toBeVisible();
    expect(screen.queryByText("999")).toBeNull();
  });

  it("СЦ-1: почта документооборота не подключена — форма говорит это до отправки, кнопка не обещает отправку", async () => {
    server.use(
      http.get("*/eds/letterhead", () =>
        HttpResponse.json({
          configured: true,
          company_name: "ООО «Демо»",
          requisites: [],
          signatory_name: null,
          signatory_position: null,
          has_logo: false,
          updated_at: null,
          mail_connected: false,
        }),
      ),
    );
    await openForm("director@demo.example", "?type=letter");

    expect(
      await screen.findByText(/Почта документооборота не подключена: письмо подпишется/),
    ).toBeVisible();
    type("Почта адресата", "gni@example.uz");
    step(/Проверка и отправка/);
    expect(screen.getByRole("button", { name: "Передать на подпись" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Зарегистрировать/ })).toBeNull();
  });

  it("помощник письма (план 1.4): «Подготовить текст» вставляет черновик, «Перевести на английский» — с обратным переводом", async () => {
    await openForm("director@demo.example", "?type=letter");
    step(/Текст и вложения/);
    fireEvent.click(screen.getByRole("button", { name: "Подготовить текст" }));
    const draft = await screen.findByRole("dialog", { name: "Подготовить текст письма" });
    fireEvent.change(within(draft).getByLabelText("О чём письмо"), {
      target: { value: "Подтвердить срок поставки" },
    });
    fireEvent.click(within(draft).getByRole("button", { name: "Подготовить" }));
    await screen.findByText("Текст вставлен — проверьте его");
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Текст" })).toHaveTextContent(
        "Просим подтвердить срок поставки.",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Перевести на английский" }));
    const translate = await screen.findByRole("dialog", { name: "Перевод на английский" });
    const back = await within(translate).findByRole("region", {
      name: "Обратный перевод — проверьте смысл",
    });
    expect(within(back).getByText(/Просим подтвердить срок поставки/)).toBeInTheDocument();
    fireEvent.click(within(translate).getByRole("button", { name: "Вставить перевод" }));
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Текст" })).toHaveTextContent(
        "Please confirm the delivery date.",
      );
    });
    expect(screen.queryByRole("button", { name: "Перевести на английский" })).toBeNull();
  });

  it("автор готовит черновик и передаёт его на подпись; письмо номера не получает (СЦ-9)", async () => {
    const { router } = await openForm("manager@demo.example", "?type=letter&reply_to=ВХ-112/26");

    expect(
      screen.getByText(
        "Письмо подготовите вы, подпишет уполномоченный: номер и отправка — после подписи.",
      ),
    ).toBeVisible();
    expect(screen.getByLabelText("В ответ на входящее")).toHaveValue("ВХ-112/26");
    type("Тема", "Ответ на требование");
    await pickAddressee();
    type("Текст", "Направляем пояснения.");
    await press("Передать на подпись");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/documents");
    });
    const saved = readEds().documents.find((d) => d.subject === "Ответ на требование");
    expect(saved?.status).toBe("draft");
    expect(saved?.number).toBeNull();
    expect(saved?.letter?.registration_requested).not.toBeNull();
    expect(saved?.replyTo).toBe("ВХ-112/26");
  });

  it("делопроизводитель и директор тоже передают письмо на подпись: «Зарегистрировать» у письма нет (СЦ-9)", async () => {
    const { router } = await openForm("registrar@demo.example", "?type=letter");

    expect(
      screen.getByText(
        "Письмо подготовите вы, подпишет уполномоченный: номер и отправка — после подписи.",
      ),
    ).toBeVisible();
    type("Тема", "Запрос в банк");
    await pickAddressee();
    type("Текст", "Просим выслать выписку.");
    await press("Передать на подпись");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/documents");
    });
    const saved = readEds().documents.find((d) => d.subject === "Запрос в банк");
    expect(saved?.status).toBe("draft");
    expect(saved?.number).toBeNull();
    expect(saved?.letter?.registration_requested).not.toBeNull();
  });

  it("автор с правом подписи: главная кнопка «Подписать и отправить» открывает карточку с окном подписания (Б-8)", async () => {
    const { router } = await openForm("director@demo.example", "?type=letter");
    type("Тема", "Ответ в банк");
    await pickAddressee();
    type("Текст", "Направляем реквизиты.");
    // право подписи у документа появляется вместе с черновиком: форма сама сохраняет его при сборке PDF
    step(/Проверка и отправка/);
    const primary = await screen.findByRole("button", { name: /Подписать и отправить$/ });
    await waitFor(() => {
      expect(primary).toBeEnabled();
    });
    fireEvent.click(primary);

    await waitFor(
      () => {
        expect(router.state.location.pathname).toBe("/eds/documents");
      },
      { timeout: 5000 },
    );
    expect(router.state.location.search).toContain("sign=1");
    expect(
      await screen.findByRole("dialog", { name: "Подписание исходящего письма" }),
    ).toBeInTheDocument();
    expect(readEds().documents.find((d) => d.subject === "Ответ в банк")?.status).toBe("draft");
  });

  it("«Подготовить ответ»: форма заполнена из входящего — корреспондент, ИНН, почта, тема; можно поправить (EDS-REPLY-1)", async () => {
    const letter = readLetters().find((l) => l.number === "ВХ-108/26");
    if (!letter) throw new Error("нет письма в моках");
    writeLetters(
      readLetters().map((l) =>
        l.number === "ВХ-108/26"
          ? {
              ...l,
              sender: {
                name: "ГНИ Демо-района",
                inn: "300111222",
                contact: "gni@demo-inspection.example",
                company_id: null,
                contact_id: null,
              },
            }
          : l,
      ),
    );
    const { router } = await openForm(
      "manager@demo.example",
      `?type=letter&reply_to=${encodeURIComponent("ВХ-108/26")}&reply_id=${letter.id}`,
    );

    // имя из письма стоит в поле подсказкой: компания ещё не выбрана
    const field = await screen.findByLabelText("Адресат (организация)");
    expect(
      field.closest(".ant-select")?.querySelector(".ant-select-selection-placeholder"),
    ).toHaveTextContent("ГНИ Демо-района");
    expect(screen.getByLabelText("Почта адресата")).toHaveValue("gni@demo-inspection.example");
    expect(screen.getByLabelText("Тема")).toHaveValue(
      `На № 04-12/3456 от 28.10.2026: ${letter.subject}`,
    );
    expect(screen.getByLabelText("В ответ на входящее")).toHaveValue("ВХ-108/26");
    expect(
      screen.getByText(/Заполнено из ВХ-108\/26: проверьте корреспондента, почту и тему/),
    ).toBeVisible();

    type("Тема", "Пояснения по требованию");
    type("Текст", "Направляем пояснения.");
    // корреспондента ещё нет в контрагентах — «Завести» последней строкой, название берётся из письма
    await addCompany(field, "ГНИ Демо-района", "300111222");
    expect(await screen.findByText("ИНН 300111222")).toBeVisible();
    await press("Передать на подпись");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/documents");
    });
    const saved = readEds().documents.find((d) => d.subject === "Пояснения по требованию");
    expect(saved?.recipient).toMatchObject({
      name: "ГНИ Демо-района",
      inn: "300111222",
      contact_id: null,
    });
    expect(saved?.recipient?.company_id).toBeTruthy();
    expect(saved?.letter?.recipient_email).toBe("gni@demo-inspection.example");
    expect(saved?.replyTo).toBe("ВХ-108/26");
  });

  it("письмо не прочиталось: форма открывается с одним номером ВХ, путь не обрывается", async () => {
    server.use(
      http.get("*/eds/letters/:ref", () =>
        HttpResponse.json({ code: "NOT_FOUND", message: "x", source: "eds" }, { status: 404 }),
      ),
    );
    await openForm(
      "manager@demo.example",
      `?type=letter&reply_to=${encodeURIComponent("ВХ-108/26")}&reply_id=20000000-0000-4000-8000-000000000108`,
    );
    expect(await screen.findByLabelText("В ответ на входящее")).toHaveValue("ВХ-108/26");
    expect(selectedLabel(screen.getByLabelText("Адресат (организация)"))).toBe("");
  });

  it("страницы строятся сами после паузы: черновик сохраняется один раз, PDF готовится в фоне и показывается", async () => {
    await openForm("director@demo.example", "?type=letter");
    // форма не заполнена — ни черновика, ни ошибок у полей
    expect(
      screen.getByText(/Заполните тему, адресата и текст — письмо сохранится черновиком/),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Показать PDF" })).toBeNull();
    type("Тема", "Ответ на требование");
    await pickAddressee();
    type("Текст", "Направляем пояснения.");

    expect(await screen.findByText("Готовится PDF…", {}, { timeout: 3000 })).toBeVisible();
    expect(await screen.findByText("PDF готов · 1 стр.", {}, { timeout: 5000 })).toBeVisible();
    expect(await screen.findByTestId("pdf-pages")).toHaveTextContent(
      "Письмо «Ответ на требование»",
    );
    expect(screen.getByRole("button", { name: "Скачать PDF" })).toBeVisible();
    // правка текста: прежние страницы остаются на экране с пометкой «Обновляется…», затем — новый PDF
    type("Текст", "Направляем пояснения и копии документов.");
    expect(await screen.findByText("Обновляется…", {}, { timeout: 3000 })).toBeVisible();
    expect(screen.getByTestId("pdf-pages")).toBeInTheDocument();
    expect(await screen.findByText("PDF готов · 1 стр.", {}, { timeout: 5000 })).toBeVisible();
    // черновик создан один раз; тип больше не меняется
    expect(readEds().documents.filter((d) => d.subject === "Ответ на требование")).toHaveLength(1);
    // у письма выбора типа нет вовсе: экран «Исходящее письмо» (план 2026-11-12 п. 0.2)
    expect(screen.queryByLabelText("Тип документа")).toBeNull();
  });

  it("«Что произойдёт» и маршрут: без суммы — директор; с суммой — ещё и бухгалтер", async () => {
    await openForm("manager@demo.example");

    // маршрут — в свёрнутой строке шага «Согласование» и внутри него
    step(/Согласование/);
    const route = screen.getByRole("region", { name: /Согласование/ });
    expect(within(route).getByText("Вы → согласование")).toBeVisible();

    type("Сумма, сум", "1 500 000");

    expect(within(route).getByText("Вы → согласование → оплата (есть сумма)")).toBeVisible();
  });

  it("служебка с суммой без счёта партнёра не уходит: в «Осталось» названо, что приложить; отметка «придёт позже» снимает требование (Б-9)", async () => {
    await openForm("manager@demo.example");
    fillMemo("Оплата рельсов", "Прошу оплатить поставку.");
    type("Сумма, сум", "1 500 000");

    step(/Проверка и отправка/);
    const send = screen.getByRole("button", { name: /Отправить на согласование$/ });
    expect(send).toBeDisabled();
    expect(
      screen.getAllByText(/Приложите счёт партнёра или отметьте, что он придёт позже\./).length,
    ).toBeGreaterThan(0);

    invoiceLater();
    step(/Проверка и отправка/);
    expect(screen.getByRole("button", { name: /Отправить на согласование$/ })).toBeEnabled();
  });

  it("согласующие и получатели копии (пункт 1.6): выбор в шаге «Согласование», после отправки — в маршруте", async () => {
    await openForm("manager@demo.example");
    type("Тема", "Закупка с согласованием");
    step(/Текст и вложения/);
    type("Текст", "Прошу согласовать.");
    step(/Согласование/);
    fireEvent.mouseDown(screen.getByLabelText("Согласующие"));
    fireEvent.click(await screen.findByText(/Демо Снабженцев/));
    fireEvent.mouseDown(screen.getByLabelText("Получатели копии"));
    const watcher = (await screen.findAllByText(/Демо Инженеров/)).at(-1);
    if (!watcher) throw new Error("no watcher option");
    fireEvent.click(watcher);

    await press("Отправить на согласование");

    await waitFor(() => {
      const saved = readEds().documents.find((d) => d.subject === "Закупка с согласованием");
      expect(saved?.approvers).toEqual(["u-demo-supply"]);
      expect(saved?.watchers).toEqual(["u-demo-engineer"]);
    });
  });

  it("обязательные поля: недостающее названо на шаге и в «Осталось», кнопка недоступна, пройденный шаг не открывается заново", async () => {
    await openForm("manager@demo.example");

    step(/Проверка и отправка/);
    const main = screen.getByRole("button", { name: "Отправить на согласование" });
    expect(main).toBeDisabled();
    const list = document.getElementById("doc-remaining") as HTMLElement;
    expect(within(list).getByText(/Укажите тему\./)).toBeVisible();
    expect(within(list).getByText(/Напишите текст документа\./)).toBeVisible();
    expect(main).toHaveAttribute("aria-describedby", "doc-remaining");
    // «Осталось» ведёт на шаг; поле помечено, потому что шаг уже покидали
    fireEvent.click(within(list).getByRole("button", { name: /^О чём/ }));
    expect(screen.getByLabelText("Тема")).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/Отправлено на согласование/)).toBeNull();

    // исправили — «Осталось» пусто, кнопка доступна
    fillMemo();
    step(/Проверка и отправка/);
    expect(document.getElementById("doc-remaining")).toBeNull();
    expect(screen.getByRole("button", { name: "Отправить на согласование" })).toBeEnabled();
  });

  it("галочки шагов — по validate: сумма «0» снимает галочку «О чём»; «Согласование» без галочки, пока не пройден", async () => {
    await openForm("manager@demo.example");
    fillMemo();
    type("Сумма, сум", "0");
    step(/Текст и вложения/);
    const about = screen.getByRole("button", { name: /^О чём/ });
    expect(about).toHaveTextContent("Нужно исправить");
    expect(about.querySelector(".lucide-check")).toBeNull();
    // «Согласование» ещё не открывали — галочки нет (раньше стояла всегда)
    const route = screen.getByRole("button", { name: /^Согласование/ });
    expect(route.querySelector(".lucide-check")).toBeNull();
    step(/Согласование/);
    step(/Текст и вложения/);
    expect(
      screen.getByRole("button", { name: /^Согласование/ }).querySelector(".lucide-check"),
    ).not.toBeNull();
  });

  it("боковое окно: у формы кнопки окна нет; повторный переход из «Создать» открывает пустую форму", async () => {
    const { router } = await openForm("manager@demo.example");
    type("Тема", "Закупка");
    // форма ничего в окно не кладёт и таблицы на ней нет — «Показать панель» не рисуется (ЕВ-0)
    expect(screen.queryByRole("button", { name: /Скрыть панель|Показать панель/ })).toBeNull();
    expect(screen.getByLabelText("Тема")).toHaveValue("Закупка");
    // намеренный переход с меткой «Создать» — форма новая
    await router.navigate("/eds/new?type=memo", { state: { fresh: 1 } });
    await waitFor(() => {
      expect(screen.getByLabelText("Тема")).toHaveValue("");
    });
  });

  it("отказ сервера по полю «О чём»: у шага нет галочки и есть «Нужно исправить», пока поле не поправят", async () => {
    server.use(
      http.post("*/eds/documents", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_ERROR",
            message: "x",
            source: "eds",
            details: { fields: ["erp_deal_id"] },
          },
          { status: 422 },
        ),
      ),
    );
    await openForm("manager@demo.example");
    fillMemo();
    await press("Отправить на согласование");
    await screen.findByRole("alert");
    step(/Проверка и отправка/);
    const about = screen.getByRole("button", { name: /^О чём/ });
    expect(about).toHaveTextContent("Нужно исправить");
    expect(about.querySelector(".lucide-check")).toBeNull();
  });

  it("сумма больше нуля и «нужно до» не в прошлом", async () => {
    await openForm("manager@demo.example");
    fillMemo();
    type("Сумма, сум", "0");
    const due = screen.getByLabelText("Нужно до");
    // Дни раньше сегодня по Ташкенту в календаре отключены — прошедший срок не выбрать.
    fireEvent.mouseDown(due);
    fireEvent.click(due);
    const today = companyToday();
    const [y = 0, m = 1, d = 1] = today.split("-").map(Number);
    const yesterday = new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10);
    const cell = (day: string) =>
      document.querySelector<HTMLElement>(`.ant-picker-cell[title="${day}"]`);
    await waitFor(() => {
      expect(cell(yesterday)).toHaveClass("ant-picker-cell-disabled");
    });
    expect(cell(today)).not.toHaveClass("ant-picker-cell-disabled");
    fillDate(due, "2020-01-01");

    fireEvent.click(screen.getByRole("button", { name: "Сохранить черновик" }));

    // текст — и у поля, и в требованиях шага: шаг открыт заново нажатием
    expect(
      (await screen.findAllByText("Сумма должна быть больше нуля, например 1 500 000."))[0],
    ).toBeVisible();
    expect(screen.getAllByText("Срок «нужно до» не может быть в прошлом.")[0]).toBeVisible();
    expect(due).toHaveValue("01.01.2020");
  });

  it("отправка: записка с суммой уходит на согласование, открывается документ в боковом окне со статусом словами", async () => {
    const { router } = await openForm("manager@demo.example");
    fillMemo("Закупка мебели для переговорной", "Прошу согласовать закупку трёх столов.");
    type("Сумма, сум", "3 600 000");
    invoiceLater();

    await press("Отправить на согласование");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/documents");
    });
    expect(router.state.location.search).toContain("scope=mine");
    expect(
      await screen.findByRole("heading", { level: 3, name: "Закупка мебели для переговорной" }),
    ).toBeVisible();
    const panel = document.getElementById("pf-context-panel");
    expect(panel).not.toBeNull();
    expect(within(panel as HTMLElement).getByText("На согласовании")).toBeVisible();
    expect(within(panel as HTMLElement).getByText("Директор — ждёт решения")).toBeVisible();
    expect(within(panel as HTMLElement).getByText("Бухгалтер — дальше по маршруту")).toBeVisible();
  });

  it("сбой сервера: «Не отправлено: …», введённое остаётся, повтор идёт по сохранённому черновику и проходит", async () => {
    const { router } = await openForm("manager@demo.example");
    fillMemo("Командировка", "Нужна командировка. [сбой]");
    type("Сумма, сум", "500 000");
    invoiceLater();

    await press("Отправить на согласование");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Не отправлено: сервис документов не отвечает, повторите чуть позже",
    );
    expect(alert).toHaveTextContent("Черновик сохранён, введённое не потеряно");
    expect(screen.getByLabelText("Тема")).toHaveValue("Командировка");
    expect(screen.getByLabelText("Текст")).toHaveValue("Нужна командировка. [сбой]");
    expect(screen.getByLabelText("Сумма, сум")).toHaveValue("500 000");
    expect(router.state.location.pathname).toBe("/eds/new");
    // документ уже создан: тип менять нельзя, иначе повтор ушёл бы в другой документ
    expect(screen.getByLabelText("Тип документа")).toBeDisabled();

    type("Текст", "Нужна командировка.");
    await press("Отправить на согласование");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/documents");
    });
    expect(await screen.findByRole("heading", { level: 3, name: "Командировка" })).toBeVisible();
    // документ один: повтор не создал второй
    cleanup();
    const second = renderAt("/eds/documents?scope=mine&kind=memo");
    await screen.findByRole("heading", { level: 1, name: "Все документы" });
    expect(
      await screen.findAllByRole("link", { name: "Открыть документ: Командировка" }),
    ).toHaveLength(1);
    second.router.dispose();
  });

  it("сохранение черновика: ничего не отправляется, форма остаётся открытой, второе нажатие обновляет тот же черновик (Б-8)", async () => {
    const { router } = await openForm("manager@demo.example");
    fillMemo("Черновик заявки на ноутбук", "Нужен ноутбук для нового сотрудника.");

    fireEvent.click(screen.getByRole("button", { name: "Сохранить черновик" }));

    expect(await screen.findByText("Черновик сохранён")).toBeVisible();
    expect(router.state.location.pathname).toBe("/eds/new");
    expect(screen.getByLabelText("Тема")).toHaveValue("Черновик заявки на ноутбук");
    // дописали и сохранили ещё раз — форма по-прежнему на месте
    type("Тема", "Черновик заявки на ноутбук Lenovo");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить черновик" }));
    await waitFor(() => {
      expect(screen.getAllByText("Черновик сохранён").length).toBeGreaterThan(0);
    });
    expect(router.state.location.pathname).toBe("/eds/new");
    expect(screen.getByLabelText("Тема")).toHaveValue("Черновик заявки на ноутбук Lenovo");
  });

  it("вложение: файл загружается сразу, его можно убрать; слишком большой не отправляется", async () => {
    await openForm("manager@demo.example");
    step(/Текст и вложения/);
    const input = screen.getByLabelText("Вложения");

    fireEvent.change(input, {
      target: { files: [new File(["%PDF-1.4"], "schet.pdf", { type: "application/pdf" })] },
    });

    const list = await screen.findByRole("list", { name: "Прикреплённые файлы" });
    expect(within(list).getByText("schet.pdf")).toBeVisible();
    expect(await within(list).findByText("загружен")).toBeVisible();

    const huge = new File(["x"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(huge, "size", { value: 26 * 1024 * 1024 });
    fireEvent.change(input, { target: { files: [huge] } });
    expect(await within(list).findByText("Файл больше 25 МБ.")).toBeVisible();

    fireEvent.change(input, {
      target: { files: [new File(["MZ"], "virus.exe", { type: "application/x-msdownload" })] },
    });
    expect(
      await within(list).findByText("Допустимы PDF, изображения и файлы Word, Excel и PowerPoint."),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Убрать файл schet.pdf" }));
    expect(within(list).queryByText("schet.pdf")).toBeNull();
  });

  it("«Продолжить» черновик: форма заполнена данными, тип нельзя менять, вложение отмечено как уже в документе", async () => {
    // черновик менеджера из демо-данных: «Ремонт кондиционера в переговорной», № СЗ-2026/033
    await openForm("manager@demo.example", "?draft=00000000-0000-4000-8000-000000000004");

    // черновик открывается на шаге «Проверка и отправка»; поля заполнены
    expect(
      await screen.findByDisplayValue("Ремонт кондиционера в переговорной"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Текст")).toHaveValue(
      "Нужно заменить компрессор в кондиционере переговорной комнаты.",
    );
    expect(screen.getByLabelText("Сумма, сум")).toHaveValue("1200000");
    expect(
      screen.getByText("Черновик СЗ-2026/033: правки сохраняются, отправить можно в любой момент."),
    ).toBeVisible();
    step(/О чём/);
    expect(screen.getByText("Тип нельзя менять после создания.")).toBeVisible();
  });

  it("чужой или отправленный документ править нельзя: словами и со ссылкой на «К документам»", async () => {
    // СЗ-2026/031 уже на согласовании
    await openForm("manager@demo.example", "?draft=00000000-0000-4000-8000-000000000001");

    expect(await screen.findByText("Этот документ нельзя править")).toBeVisible();
    expect(screen.getByRole("link", { name: "К документам" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Отправить на согласование" })).toBeNull();
  });

  it("роль без разделов EDS получает «Нет доступа» вместо формы", async () => {
    const { readRoles, writeRoles } = await import("../../../mocks/fixtures/roles");
    writeRoles(
      readRoles().map((role) =>
        role.demo === "MANAGER" ? { ...role, access: { "dashboard.queue": "full" } } : role,
      ),
    );
    signIn("manager@demo.example");
    renderAt("/eds/new");

    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByLabelText("Тема")).toBeNull();
  });

  it("ключ повтора создания: тот же при повторе с тем же телом, новый — если форму изменили", async () => {
    const keys: (string | null)[] = [];
    server.use(
      http.post("*/eds/documents", ({ request }) => {
        keys.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "x", source: "eds" },
          { status: 503 },
        );
      }),
    );
    await openForm("manager@demo.example");
    fillMemo("Командировка", "Нужна командировка.");

    const send = async () => {
      await press("Отправить на согласование");
      await waitFor(() => {
        expect(keys.length).toBeGreaterThan(sent);
      });
      sent = keys.length;
      await screen.findByRole("alert");
    };
    let sent = 0;
    await send();
    await send();
    type("Текст", "Нужна командировка на два дня.");
    await send();

    expect(keys[0]).toMatch(/.{8,}/);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });
});

describe("два экрана: исходящее письмо и внутренний документ (план 2026-11-12 п. 0.2)", () => {
  it("письмо — свой заголовок и без выбора типа; внутренний документ — тип из трёх внутренних", async () => {
    await openForm("registrar@demo.example", "?type=letter");
    expect(screen.getByRole("heading", { level: 1, name: "Исходящее письмо" })).toBeVisible();
    expect(screen.queryByLabelText("Тип документа")).toBeNull();
  });

  it("внутренний документ: заголовок и поле «Тип документа»", async () => {
    await openForm("manager@demo.example", "?type=report");
    expect(screen.getByRole("heading", { level: 1, name: "Внутренний документ" })).toBeVisible();
    expect(screen.getByLabelText("Тип документа")).toBeInTheDocument();
    expect(screen.getAllByText("Отчёт").length).toBeGreaterThan(0);
  });
});
