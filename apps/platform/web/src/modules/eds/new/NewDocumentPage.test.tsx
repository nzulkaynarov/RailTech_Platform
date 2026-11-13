import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HttpResponse, http } from "msw";

import { companyToday } from "../../../shared/lib/dates";
import { fillDate } from "../../../test/fields";
import { server } from "../../../test/server";
import { readEds } from "../../../mocks/fixtures/edsDocuments";
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
      onChange,
      invalid,
      describedBy,
    }: {
      id: string;
      label: string;
      onChange: (doc: unknown) => void;
      invalid?: boolean;
      describedBy?: string;
    }) => (
      <textarea
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
    expect(screen.getByLabelText("Кому")).toHaveValue("Директор");
    expect(screen.getByLabelText("Кому")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Сумма, сум")).toBeVisible();
    expect(screen.getByLabelText("Нужно до")).toBeVisible();
    // менеджеру открыты заявки: поле «Связь с проектом» есть
    expect(screen.getByLabelText("Связь с проектом")).toBeInTheDocument();
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

  it("адресат письма из контрагентов: подсказка по названию подставляет ИНН, почту и «Кому»; вручную — тоже можно", async () => {
    await openForm("director@demo.example", "?type=letter");
    type("Адресат (организация)", "демо");
    fireEvent.click(await screen.findByText("АО «Демо-Путь»"));
    expect(screen.getByLabelText("Адресат (организация)")).toHaveValue("АО «Демо-Путь»");
    expect(screen.getByLabelText("ИНН адресата")).toHaveValue("300000777");
    expect(screen.getByLabelText("Почта адресата")).toHaveValue("office@demo-put.example");
    expect(screen.getByLabelText("Кому (должность и ФИО)")).toHaveValue("Демо Клиентов");
    // адресата нет в книге — пишем вручную, подсказки не мешают
    type("Адресат (организация)", "ГНИ Мирабадского района");
    expect(screen.getByLabelText("Адресат (организация)")).toHaveValue("ГНИ Мирабадского района");
  });

  it("?type=letter у роли с доступом к входящим: письмо на бланке — адресат, почта, «кому», блоки, подписант; без суммы и срока", async () => {
    await openForm("director@demo.example", "?type=letter");

    expect(screen.getByLabelText("Адресат (организация)")).toBeVisible();
    expect(screen.getByLabelText("Почта адресата")).toBeVisible();
    expect(screen.getByLabelText("Кому (должность и ФИО)")).toBeVisible();
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
    expect(screen.getByRole("button", { name: "Зарегистрировать письмо" })).toBeVisible();
    type("Почта адресата", "gni@example.uz");
    expect(screen.getByRole("button", { name: "Зарегистрировать и отправить" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Отправить на согласование" })).toBeNull();
    expect(screen.getByRole("region", { name: "PDF на бланке" })).toBeVisible();
  });

  it("у роли без права регистрировать письмо готовит черновик и передаёт его на регистрацию (B-P8B-4)", async () => {
    const { router } = await openForm("manager@demo.example", "?type=letter&reply_to=ВХ-112/26");

    expect(
      screen.getByText("Письмо подготовите вы, зарегистрирует и отправит делопроизводитель."),
    ).toBeVisible();
    expect(screen.getByLabelText("В ответ на входящее")).toHaveValue("ВХ-112/26");
    type("Тема", "Ответ на требование");
    type("Адресат (организация)", "ГНИ Мирабадского района");
    type("Текст", "Направляем пояснения.");
    await press("Передать на регистрацию");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/documents");
    });
    const saved = readEds().documents.find((d) => d.subject === "Ответ на требование");
    expect(saved?.status).toBe("draft");
    expect(saved?.letter?.registration_requested).not.toBeNull();
    expect(saved?.replyTo).toBe("ВХ-112/26");
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
              },
            }
          : l,
      ),
    );
    const { router } = await openForm(
      "manager@demo.example",
      `?type=letter&reply_to=${encodeURIComponent("ВХ-108/26")}&reply_id=${letter.id}`,
    );

    expect(await screen.findByLabelText("Адресат (организация)")).toHaveValue("ГНИ Демо-района");
    expect(screen.getByLabelText("ИНН адресата")).toHaveValue("300111222");
    expect(screen.getByLabelText("Почта адресата")).toHaveValue("gni@demo-inspection.example");
    expect(screen.getByLabelText("Тема")).toHaveValue(
      `На ВХ-108/26 от 29.10.2026: ${letter.subject}`,
    );
    expect(screen.getByLabelText("В ответ на входящее")).toHaveValue("ВХ-108/26");
    expect(
      screen.getByText(/Заполнено из ВХ-108\/26: проверьте корреспондента, почту и тему/),
    ).toBeVisible();

    type("Тема", "Пояснения по требованию");
    type("Текст", "Направляем пояснения.");
    await press("Передать на регистрацию");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/documents");
    });
    const saved = readEds().documents.find((d) => d.subject === "Пояснения по требованию");
    expect(saved?.recipient).toEqual({ name: "ГНИ Демо-района", inn: "300111222" });
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
    expect(screen.getByLabelText("Адресат (организация)")).toHaveValue("");
  });

  it("«Показать PDF»: черновик сохраняется, PDF готовится в фоне и показывается со страницами", async () => {
    await openForm("director@demo.example", "?type=letter");
    type("Тема", "Ответ на требование");
    type("Адресат (организация)", "ГНИ Мирабадского района");
    type("Текст", "Направляем пояснения.");

    fireEvent.click(screen.getByRole("button", { name: "Показать PDF" }));

    expect(await screen.findByText("Готовится PDF…")).toBeVisible();
    expect(await screen.findByText("PDF готов · 1 стр.", {}, { timeout: 5000 })).toBeVisible();
    expect(await screen.findByTestId("pdf-pages")).toHaveTextContent(
      "Письмо «Ответ на требование»",
    );
    expect(screen.getByRole("button", { name: "Скачать PDF" })).toBeVisible();
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
    expect(within(route).getByText("Вы → Директор")).toBeVisible();

    type("Сумма, сум", "1 500 000");

    expect(within(route).getByText("Вы → Директор → Бухгалтер (есть сумма)")).toBeVisible();
  });

  it("обязательные поля: пустая отправка подсвечивает тему и текст, ничего не уходит на сервер", async () => {
    await openForm("manager@demo.example");

    await press("Отправить на согласование");

    // ошибка открывает свою секцию: тема — шаг 1; у шага 2 отметка «Нужно исправить»
    expect(await screen.findByText("Укажите тему.")).toBeVisible();
    expect(screen.getByRole("button", { name: /Текст и вложения.*Нужно исправить/ })).toBeVisible();
    step(/Текст и вложения/);
    expect(screen.getByText("Напишите текст документа.")).toBeVisible();
    expect(screen.getByLabelText("Тема")).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => {
      expect(screen.getByLabelText("Тема")).toHaveFocus();
    });
    expect(screen.queryByText(/Отправлено на согласование/)).toBeNull();
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

    expect(
      await screen.findByText("Сумма должна быть больше нуля, например 1 500 000."),
    ).toBeVisible();
    expect(screen.getByText("Срок «нужно до» не может быть в прошлом.")).toBeVisible();
    expect(due).toHaveValue("01.01.2020");
  });

  it("отправка: служебка с суммой уходит на согласование, открывается документ в боковом окне со статусом словами", async () => {
    const { router } = await openForm("manager@demo.example");
    fillMemo("Закупка мебели для переговорной", "Прошу согласовать закупку трёх столов.");
    type("Сумма, сум", "3 600 000");

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

  it("сохранение черновика: ничего не отправляется, документ остаётся «Черновиком» и открывается карточкой", async () => {
    const { router } = await openForm("manager@demo.example");
    fillMemo("Черновик заявки на ноутбук", "Нужен ноутбук для нового сотрудника.");

    fireEvent.click(screen.getByRole("button", { name: "Сохранить черновик" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/documents");
    });
    const heading = await screen.findByRole("heading", {
      level: 3,
      name: "Черновик заявки на ноутбук",
    });
    const panel = heading.closest("#pf-context-panel") as HTMLElement;
    expect(within(panel).getByText("Черновик")).toBeVisible();
    expect(within(panel).getByRole("link", { name: "Продолжить" })).toBeVisible();
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
      await within(list).findByText("Допустимы PDF, изображения и документы Office."),
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
