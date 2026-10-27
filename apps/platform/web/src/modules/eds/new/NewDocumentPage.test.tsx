import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupEdsTests, signIn } from "../../../test/edsKit";

setupEdsTests();

async function openForm(email: string, search = "") {
  signIn(email);
  const view = renderAt(`/eds/new${search}`);
  expect(await screen.findByRole("heading", { level: 1, name: "Создать документ" })).toBeVisible();
  return view;
}

function type(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function fillMemo(subject = "Закупка канцтоваров", text = "Прошу согласовать закупку.") {
  type("Тема", subject);
  type("Текст", text);
}

describe("EDS · Создать документ: форма", () => {
  it("служебная записка по умолчанию: тема, кому (директор), текст, сумма, срок, вложения, главная и вторичная кнопки", async () => {
    await openForm("manager@demo.example");

    expect(screen.getByLabelText("Тип документа")).toBeInTheDocument();
    expect(screen.getByLabelText("Тема")).toBeVisible();
    expect(screen.getByLabelText("Кому")).toHaveValue("Директор");
    expect(screen.getByLabelText("Кому")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Текст")).toBeVisible();
    expect(screen.getByLabelText("Сумма, сум")).toBeVisible();
    expect(screen.getByLabelText("Нужно до")).toBeVisible();
    expect(screen.getByLabelText("Вложения")).toBeVisible();
    expect(screen.getByRole("button", { name: "Отправить на согласование" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Сохранить черновик" })).toBeVisible();
    // менеджеру открыты заявки: поле «Связь с проектом» есть
    expect(screen.getByLabelText("Связь с проектом")).toBeInTheDocument();
  });

  it("?type=letter у роли с доступом к входящим: адресат вместо «Кому», без суммы и срока, кнопка «Зарегистрировать письмо»", async () => {
    await openForm("director@demo.example", "?type=letter");

    expect(screen.getByLabelText("Адресат (организация)")).toBeVisible();
    expect(screen.queryByLabelText("Кому")).toBeNull();
    expect(screen.queryByLabelText("Сумма, сум")).toBeNull();
    expect(screen.queryByLabelText("Нужно до")).toBeNull();
    expect(screen.getByRole("button", { name: "Зарегистрировать письмо" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Отправить на согласование" })).toBeNull();
  });

  it("у роли без доступа к входящим письмо недоступно: ?type=letter открывает служебную записку", async () => {
    await openForm("manager@demo.example", "?type=letter");

    expect(screen.getByLabelText("Кому")).toBeVisible();
    expect(
      screen.getByText("Письма регистрирует роль с доступом к входящим письмам."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Отправить на согласование" })).toBeVisible();
  });

  it("«Что произойдёт» и маршрут: без суммы — директор; с суммой — ещё и бухгалтер", async () => {
    await openForm("manager@demo.example");

    const block = screen.getByRole("group", { name: "Что произойдёт" });
    expect(screen.getByText("Вы → Директор")).toBeVisible();
    expect(within(block).queryByText(/бухгалтеру/)).toBeNull();

    type("Сумма, сум", "1 500 000");

    expect(screen.getByText("Вы → Директор → Бухгалтер (есть сумма)")).toBeVisible();
    expect(
      within(screen.getByRole("group", { name: "Что произойдёт" })).getByText(
        "После согласования директором документ передадут бухгалтеру — к оплате.",
      ),
    ).toBeVisible();
  });

  it("обязательные поля: пустая отправка подсвечивает тему и текст, ничего не уходит на сервер", async () => {
    await openForm("manager@demo.example");

    fireEvent.click(screen.getByRole("button", { name: "Отправить на согласование" }));

    expect(await screen.findByText("Укажите тему.")).toBeVisible();
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
    type("Нужно до", "2020-01-01");

    fireEvent.click(screen.getByRole("button", { name: "Сохранить черновик" }));

    expect(
      await screen.findByText("Сумма должна быть больше нуля, например 1 500 000."),
    ).toBeVisible();
    expect(screen.getByText("Срок «нужно до» не может быть в прошлом.")).toBeVisible();
    expect(screen.getByLabelText("Нужно до")).toHaveAttribute("min");
  });

  it("отправка: служебка с суммой уходит на согласование, открывается документ в боковом окне со статусом словами", async () => {
    const { router } = await openForm("manager@demo.example");
    fillMemo("Закупка мебели для переговорной", "Прошу согласовать закупку трёх столов.");
    type("Сумма, сум", "3 600 000");

    fireEvent.click(screen.getByRole("button", { name: "Отправить на согласование" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Отправить на согласование" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Не отправлено: сервис документов не отвечает, повторите чуть позже",
    );
    expect(alert).toHaveTextContent("Черновик сохранён, введённое не потеряно");
    expect(screen.getByLabelText("Тема")).toHaveValue("Командировка");
    expect(screen.getByLabelText("Текст")).toHaveValue("Нужна командировка. [сбой]");
    expect(screen.getByLabelText("Сумма, сум")).toHaveValue("500 000");
    expect(router.state.location.pathname).toBe("/eds/new");

    type("Текст", "Нужна командировка.");
    // Значок загрузки уходит с анимацией, которой в jsdom нет: имя кнопки на миг содержит «loading».
    fireEvent.click(await screen.findByRole("button", { name: /Отправить на согласование/ }));

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

    expect(await screen.findByDisplayValue("Ремонт кондиционера в переговорной")).toBeVisible();
    expect(screen.getByLabelText("Текст")).toHaveValue(
      "Нужно заменить компрессор в кондиционере переговорной комнаты.",
    );
    expect(screen.getByLabelText("Сумма, сум")).toHaveValue("1200000");
    expect(
      screen.getByText("Черновик СЗ-2026/033: правки сохраняются, отправить можно в любой момент."),
    ).toBeVisible();
    expect(screen.getByText("Тип нельзя менять после создания.")).toBeVisible();
  });

  it("чужой или отправленный документ править нельзя: словами и со ссылкой на «Мои документы»", async () => {
    // СЗ-2026/031 уже на согласовании
    await openForm("manager@demo.example", "?draft=00000000-0000-4000-8000-000000000001");

    expect(await screen.findByText("Этот документ нельзя править")).toBeVisible();
    expect(screen.getByRole("link", { name: "Мои документы" })).toBeVisible();
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
});
