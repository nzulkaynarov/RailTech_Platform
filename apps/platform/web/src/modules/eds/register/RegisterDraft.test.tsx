import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import type { LetterRegisterIn } from "../../../shared/api/generated/model";
import { addCompany, chooseOption, selectedLabel } from "../../../test/fields";
import { setupLetterTests } from "../../../test/lettersKit";
import { renderAt, signIn } from "../../../test/edsKit";
import { server } from "../../../test/server";
import { openStep, reveal } from "../../../test/steps";
import { resetEds } from "../../../mocks/fixtures/edsDocuments";
import { currentActor } from "../../../mocks/mockSession";
import { emptyRegister } from "./registerModel";
import { readRegisterDraft, REGISTER_DRAFT_TTL_MS, writeRegisterDraft } from "./draft";

setupLetterTests();

const TITLE = "Регистрация входящего документа";
const DRAFT = /^Черновик от .*: trebovanie\.pdf$/;

async function open(path = "/eds/register") {
  signIn("registrar@demo.example");
  renderAt(path);
  expect(await screen.findByRole("heading", { level: 1, name: TITLE })).toBeVisible();
}

async function attach(name = "trebovanie.pdf") {
  fireEvent.change(reveal(screen.getByLabelText("Файл документа")), {
    target: { files: [new File(["%PDF-1.4"], name, { type: "application/pdf" })] },
  });
  const list = await screen.findByRole("list", { name: "Прикреплённые файлы" });
  await waitFor(() => {
    expect(within(list).getAllByText("загружен").length).toBeGreaterThan(0);
  });
}

function intakeCalls(): { count: number } {
  const calls = { count: 0 };
  server.events.on("request:start", ({ request }) => {
    if (request.method === "POST" && new URL(request.url).pathname.endsWith("/eds/letter-intake"))
      calls.count += 1;
  });
  return calls;
}

async function addSender(name: string) {
  await addCompany(reveal(screen.getByLabelText("Корреспондент (организация)")), name);
}

let senders = 0;

async function fillAndLeave() {
  resetEds();
  await open();
  await chooseOption(
    reveal(screen.getByLabelText("Вид документа")),
    "Требование или уведомление ГНК",
  );
  await attach();
  expect(await screen.findByText(/Заполнено из файла:/)).toBeVisible();
  senders += 1;
  await addSender(`ГНИ Тестового района ${String(senders)}`); // мок помнит заведённые организации между тестами
  fireEvent.change(reveal(screen.getByLabelText("Тема")), {
    target: { value: "Требование о пояснениях" },
  });
  await waitFor(() => {
    expect(window.sessionStorage.length).toBeGreaterThan(0);
  });
  cleanup();
}

describe("Черновик регистрации входящего (СЦ-10)", () => {
  it("«Продолжить» возвращает файл, вид, способ и тему; регистрация уходит с этим файлом и стирает черновик", async () => {
    await fillAndLeave();
    let body = null as LetterRegisterIn | null;
    server.use(
      http.post("*/eds/letters", async ({ request }) => {
        body = (await request.clone().json()) as LetterRegisterIn;
        return undefined;
      }),
    );
    await open();

    expect(await screen.findByText(DRAFT)).toBeVisible();
    expect(screen.queryByRole("list", { name: "Прикреплённые файлы" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));

    openStep("Файл письма");
    const list = await screen.findByRole("list", { name: "Прикреплённые файлы" });
    expect(within(list).getByText("trebovanie.pdf")).toBeInTheDocument();
    expect(selectedLabel(reveal(screen.getByLabelText("Вид документа")))).toBe(
      "Требование или уведомление ГНК",
    );
    expect(selectedLabel(reveal(screen.getByLabelText("Способ получения")))).toBe(
      "Кабинет налогоплательщика my.soliq",
    );
    expect(reveal(screen.getByLabelText("Тема"))).toHaveValue("Требование о пояснениях");

    openStep("Проверка и регистрация");
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Входящие" })).toBeVisible();
    expect(body?.file_ids).toHaveLength(1);
    expect(body?.sender_company_id).toMatch(/^\d+$/); // корреспондент — обязательный, восстановлен из черновика
    expect(
      Object.keys(window.sessionStorage).some((k) => k.startsWith("rt-pf-register-draft-v1:")),
    ).toBe(false);
  });

  it("распознавание файла при «Продолжить» не повторяется", async () => {
    const calls = intakeCalls();
    await fillAndLeave();
    const before = calls.count;
    await open();
    fireEvent.click(await screen.findByRole("button", { name: "Продолжить" }));
    openStep("Файл письма");
    await screen.findByRole("list", { name: "Прикреплённые файлы" });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(calls.count).toBe(before);
  });

  it("файл из черновика без предложения ИИ (его убрали) не распознаётся заново сам", async () => {
    resetEds();
    signIn("registrar@demo.example");
    const userId = currentActor()?.id ?? "";
    const values = {
      ...emptyRegister("2026-11-20"),
      subject: "Тема",
      attachments: [
        { key: "x", name: "trebovanie.pdf", size: 8, status: "done" as const, id: "file-1" },
      ],
    };
    writeRegisterDraft(userId, "2026-11-20", { values, active: "file", ai: null });
    const calls = intakeCalls();
    renderAt("/eds/register");
    fireEvent.click(await screen.findByRole("button", { name: "Продолжить" }));
    await screen.findByRole("list", { name: "Прикреплённые файлы" });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(calls.count).toBe(0);
  });

  it("«Начать заново» стирает черновик: форма пустая, плашки больше нет", async () => {
    await fillAndLeave();
    await open();
    fireEvent.click(await screen.findByRole("button", { name: "Начать заново" }));
    expect(screen.queryByText(DRAFT)).toBeNull();
    expect(reveal(screen.getByLabelText("Тема"))).toHaveValue("");
    cleanup();
    await open();
    expect(screen.queryByText(DRAFT)).toBeNull();
  });

  it("регистрация из почты черновик не предлагает и не трогает", async () => {
    await fillAndLeave();
    const snapshot = () =>
      Object.fromEntries(
        Object.keys(window.sessionStorage).map((k) => [k, window.sessionStorage.getItem(k)]),
      );
    const stored = snapshot();
    await open("/eds/register?mail=1");
    expect(screen.queryByText(DRAFT)).toBeNull();
    expect(snapshot()).toEqual(stored);
  });

  it("файл из черновика уже не приложить: шаг «Файл» просит загрузить заново, файл убран", async () => {
    await fillAndLeave();
    server.use(
      http.post("*/eds/letters", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "Файл недоступен",
            source: "eds",
            details: { fields: ["file_ids"] },
          },
          { status: 422 },
        ),
      ),
    );
    await open();
    fireEvent.click(await screen.findByRole("button", { name: "Продолжить" }));
    openStep("Файл письма");
    await screen.findByRole("list", { name: "Прикреплённые файлы" });
    openStep("Проверка и регистрация");
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    expect((await screen.findAllByText(/Приложите файл письма/)).length).toBeGreaterThan(0);
    expect(screen.queryByText("trebovanie.pdf")).toBeNull();
  });
});

describe("Модель черновика регистрации", () => {
  it("просроченный черновик не читается и стирается; незагруженные файлы не пишутся; пустая форма стирает запись", () => {
    const today = "2026-11-20";
    const values = {
      ...emptyRegister(today),
      subject: "Тема",
      attachments: [
        { key: "a", name: "a.pdf", size: 1, status: "done" as const, id: "f1" },
        { key: "b", name: "b.pdf", size: 1, status: "uploading" as const },
      ],
    };
    writeRegisterDraft("u1", today, { values, active: "content", ai: null });
    const draft = readRegisterDraft("u1");
    expect(draft?.values.attachments.map((file) => [file.key, file.name])).toEqual([
      ["draft-f1", "a.pdf"],
    ]);
    expect(draft?.active).toBe("content");

    const raw = JSON.parse(
      window.sessionStorage.getItem("rt-pf-register-draft-v1:u1") ?? "{}",
    ) as Record<string, unknown>;
    raw["savedAt"] = new Date(Date.now() - REGISTER_DRAFT_TTL_MS - 1000).toISOString();
    window.sessionStorage.setItem("rt-pf-register-draft-v1:u1", JSON.stringify(raw));
    expect(readRegisterDraft("u1")).toBeNull();
    expect(window.sessionStorage.getItem("rt-pf-register-draft-v1:u1")).toBeNull();

    writeRegisterDraft("u1", today, { values, active: "file", ai: null });
    writeRegisterDraft("u1", today, { values: emptyRegister(today), active: "file", ai: null });
    expect(window.sessionStorage.getItem("rt-pf-register-draft-v1:u1")).toBeNull();
  });
});
