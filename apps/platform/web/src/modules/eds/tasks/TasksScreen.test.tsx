import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { LetterCard, LetterInstruction } from "../../../shared/api/generated/model";
import { findLetter, readLetters, writeLetters } from "../../../mocks/fixtures/letters";
import { letterTaskQueueItems } from "../../../mocks/edsInstructions";
import { sessionRoles, readSession } from "../../../mocks/mockSession";
import { fillDate } from "../../../test/fields";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";
import { completeBody } from "./taskModel";

setupLetterTests();

const LETTER_ID = "20000000-0000-4000-8000-000000000108";
// Рабочий экран — по UUID письма (как в строках «Моих задач» и колокольчике); номер ВХ тоже открывает экран.
const PATH = `/eds/tasks/${LETTER_ID}`;
const director = { id: "u-demo-director", name: "Демо Директоров", initials: "ДД" };
const executor = { id: "u-demo-universal", name: "Демо Широков", initials: "ДШ" };
const accountant = { id: "u-demo-accountant", name: "Демо Бухгалтеров", initials: "ДБ" };

function instruction(patch: Partial<LetterInstruction> = {}): LetterInstruction {
  return {
    id: "i-1",
    kind: "execute",
    role: "responsible",
    person: executor,
    due: "2030-01-10",
    text: "Подготовить пояснения по НДС",
    status: "in_work",
    overdue: false,
    report: null,
    files: [],
    outgoing: null,
    executed_at: null,
    extensions: [],
    ...patch,
  };
}

function inExecution(patch: Partial<LetterCard> = {}): void {
  writeLetters(
    readLetters().map((l) =>
      l.number === "ВХ-108/26"
        ? {
            ...l,
            status: "in_execution",
            on_control: true,
            office_resolution: {
              kind: "execute",
              text: "Подготовить пояснения по НДС",
              due: "2030-01-10",
              responsible: executor,
              co_executors: [],
              acquaint: [accountant],
              decided_by: director,
              decided_at: "2026-11-01T05:00:00Z",
            },
            instructions: [instruction()],
            acquaintances: [{ person: accountant, acknowledged_at: null }],
            ...patch,
          }
        : l,
    ),
  );
}

describe("Рабочий экран поручения (P8b, SPEC-v3 §3.2a п. 3–4)", () => {
  it("исполнитель: поручение со сроком; «Исполнено» без отчёта не уходит; с отчётом — письмо «Исполнено»", async () => {
    inExecution();
    signIn("universal@demo.example");
    renderAt(PATH);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Поручение по письму ВХ-108/26" }),
    ).toBeVisible();
    const mine = screen.getByRole("form", { name: "Отметить исполнение" });
    expect(screen.getAllByText(/Срок 10\.01\.2030/).length).toBeGreaterThan(0);

    fireEvent.click(within(mine).getByRole("button", { name: "Исполнено" }));
    expect(
      await within(mine).findByText("Напишите отчёт, приложите файл или укажите номер ИСХ."),
    ).toBeVisible();

    fireEvent.change(within(mine).getByLabelText("Отчёт"), {
      target: { value: "Пояснения направлены в кабинет налогоплательщика." },
    });
    fireEvent.click(within(mine).getByRole("button", { name: "Исполнено" }));
    expect(await screen.findByText("Поручение исполнено")).toBeVisible();
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.status).toBe("executed");
    });
    expect(findLetter("ВХ-108/26")?.on_control).toBe(false);
  });

  it("срочное письмо: запросить перенос можно, с пояснением, что директор может только отклонить", async () => {
    inExecution({ urgent: true });
    signIn("universal@demo.example");
    renderAt("/eds/tasks/%D0%92%D0%A5-108%2F26");
    expect(
      await screen.findByText(
        "Письмо срочное: срок не продлевается, директор может только отклонить запрос.",
      ),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Запросить перенос" })).toBeVisible();
  });

  it("обычное письмо: «Запросить перенос» — новый срок позже текущего и причина; запрос ждёт директора", async () => {
    inExecution({ urgent: false });
    signIn("universal@demo.example");
    renderAt(PATH);
    const form = await screen.findByRole("form", { name: "Не успеваете? Запросите перенос" });
    fireEvent.click(within(form).getByRole("button", { name: "Запросить перенос" }));
    expect(await within(form).findByText("Напишите причину.")).toBeVisible();
    expect(within(form).getByText("Новый срок — позже текущего (10.01.2030).")).toBeVisible();

    fillDate(within(form).getByLabelText("Новый срок"), "2030-01-17");
    fireEvent.change(within(form).getByLabelText("Причина"), {
      target: { value: "Ждём выписку банка" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Запросить перенос" }));
    expect(await screen.findByText("Запрос переноса отправлен директору")).toBeVisible();
    expect(
      await screen.findByText("Запрос переноса на 17.01.2030 ждёт решения директора."),
    ).toBeVisible();
    expect(findLetter("ВХ-108/26")?.instructions?.[0]?.extensions[0]).toMatchObject({
      status: "pending",
      new_due: "2030-01-17",
    });
  });

  it("«Ознакомиться»: сотрудник из «Ознакомить» видит письмо и ставит отметку", async () => {
    inExecution();
    signIn("accountant@demo.example");
    renderAt(PATH);
    const button = await screen.findByRole("button", { name: "Ознакомлен(а)" });
    expect(screen.queryByRole("form", { name: "Отметить исполнение" })).toBeNull();
    fireEvent.click(button);
    expect(await screen.findByText("Отмечено: ознакомлен(а)")).toBeVisible();
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.acquaintances?.[0]?.acknowledged_at).not.toBeNull();
    });
  });

  it("«Мои задачи»: строки поручения, ознакомления и переноса — без дублей, ведут на рабочий экран", () => {
    inExecution({
      urgent: false,
      instructions: [
        instruction({
          extensions: [
            {
              id: "e-1",
              old_due: "2030-01-10",
              new_due: "2030-01-17",
              reason: "Ждём выписку",
              status: "pending",
              requested_by: executor,
              requested_at: "2026-11-02T05:00:00Z",
              decided_by: null,
              decided_at: null,
              comment: null,
            },
          ],
        }),
      ],
    });
    const rows = (email: string) => {
      signIn(email);
      const session = readSession();
      const roles = session ? sessionRoles(session) : undefined;
      return letterTaskQueueItems(roles?.view ?? []);
    };
    const mine = rows("universal@demo.example");
    expect(mine.map((r) => [r.kind, r.object.path])).toEqual([
      ["instruction", `/eds/tasks/${LETTER_ID}`],
    ]);
    expect(rows("accountant@demo.example").map((r) => r.kind)).toEqual(["acquaint"]);
    expect(rows("director@demo.example").map((r) => r.kind)).toEqual(["instruction_extension"]);
  });

  it("тело «Исполнено»: отчёт, файлы или ИСХ — хотя бы одно", () => {
    expect(completeBody(" ", [], "")).toBeNull();
    expect(completeBody("", [], "ИСХ-014/26")).toEqual({
      report: null,
      file_ids: [],
      outgoing_number: "ИСХ-014/26",
    });
    expect(
      completeBody("Готово", [{ key: "a", name: "a.pdf", size: 1, status: "done", id: "f1" }], ""),
    ).toEqual({ report: "Готово", file_ids: ["f1"], outgoing_number: null });
  });
});
