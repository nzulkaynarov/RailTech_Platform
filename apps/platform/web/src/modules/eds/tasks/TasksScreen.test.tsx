import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type {
  EdsDocumentMailing,
  LetterCard,
  LetterInstruction,
} from "../../../shared/api/generated/model";
import {
  type MockDocument,
  documentId,
  readEds,
  writeEds,
} from "../../../mocks/fixtures/edsDocuments";
import { findLetter, readLetters, writeLetters } from "../../../mocks/fixtures/letters";
import { letterTaskQueueItems } from "../../../mocks/edsInstructions";
import { sessionRoles, readSession } from "../../../mocks/mockSession";
import { chooseOption, fillDate } from "../../../test/fields";
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
    // Делопроизводство: отправитель — «Корреспондент» (ГОСТ Р 7.0.97), не «Клиент».
    expect(screen.getByText("Корреспондент")).toBeVisible();
    expect(screen.queryByText("Клиент")).toBeNull();

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

  it("«К исполнению»: письмо целиком на экране и «Ответить», как у «Подготовить ответ» (решение 2026-11-11)", async () => {
    const lines = Array.from({ length: 20 }, (_, i) => `Строка письма ${String(i + 1)}`);
    inExecution({ body_text: lines.join("\n") });
    signIn("universal@demo.example");
    renderAt(PATH);
    const heading = await screen.findByRole("heading", { level: 2, name: "Письмо" });
    const card = heading.closest(".ant-card") as HTMLElement;
    expect(within(card).getByText(/Строка письма 12/)).toBeVisible();
    expect(within(card).queryByText(/Строка письма 13/)).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "Показать письмо полностью" }));
    expect(within(card).getByText(/Строка письма 20/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Ответить" })).toHaveAttribute(
      "href",
      `/eds/new?type=letter&reply_to=${encodeURIComponent("ВХ-108/26")}&reply_id=${LETTER_ID}`,
    );
  });

  it("письмо без текста (бумажное): вместо текста — краткое содержание", async () => {
    inExecution({ body_text: null, summary: "Требование пояснений по НДС" });
    signIn("universal@demo.example");
    renderAt(PATH);
    const heading = await screen.findByRole("heading", { level: 2, name: "Письмо" });
    const card = heading.closest(".ant-card") as HTMLElement;
    expect(within(card).getByText("Требование пояснений по НДС")).toBeVisible();
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

  it("«Задачи»: строки поручения, ознакомления и переноса — без дублей, ведут на рабочий экран", () => {
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

  describe("EDS-REPLY-1: ответ на входящее", () => {
    function seedReply(patch: Partial<MockDocument> = {}, mailing?: EdsDocumentMailing): void {
      const state = readEds();
      state.documents.push({
        id: documentId(950),
        kind: "letter_out",
        number: null,
        status: "draft",
        version: 1,
        subject: "Пояснения по НДС",
        text: "Пояснения.",
        ownerId: "u-demo-universal",
        amount: null,
        due_date: null,
        file_ids: [],
        erp_deal_id: null,
        recipient: { name: "ГНИ Демо-района", inn: null },
        decisions: [],
        created_at: "2026-11-02T05:00:00Z",
        updated_at: "2026-11-02T05:00:00Z",
        replyTo: "ВХ-108/26",
        letter: {
          body: null,
          recipient_attention: null,
          recipient_email: "gni@example.uz",
          signatory_name: null,
          signatory_position: null,
          pdf: null,
          pdfPolls: 0,
          mailings: mailing ? [mailing] : [],
          registration_requested: null,
        },
        ...patch,
      });
      writeEds(state);
    }
    const replyInstruction = () => instruction({ kind: "reply", text: "Подготовить ответ" });

    it("ответа нет: «Ответить» передаёт форме id письма, чтобы она заполнилась из него", async () => {
      inExecution({ instructions: [replyInstruction()] });
      signIn("universal@demo.example");
      renderAt(PATH);
      const link = await screen.findByRole("link", { name: "Ответить" });
      expect(link).toHaveAttribute(
        "href",
        `/eds/new?type=letter&reply_to=${encodeURIComponent("ВХ-108/26")}&reply_id=${LETTER_ID}`,
      );
      expect(screen.queryByRole("heading", { name: "Ответ на письмо" })).toBeNull();
    });

    it("свой черновик уже есть: «Продолжить ответ» вместо второго черновика, блок «Ответ» говорит, где он", async () => {
      inExecution({ instructions: [replyInstruction()] });
      seedReply();
      signIn("universal@demo.example");
      renderAt(PATH);
      const block = await screen.findByRole("heading", { level: 2, name: "Ответ на письмо" });
      expect(screen.queryByRole("link", { name: "Ответить" })).toBeNull();
      const card = block.closest(".ant-card") as HTMLElement;
      expect(within(card).getByText(/Черновик ответа/)).toBeVisible();
      const links = screen.getAllByRole("link", { name: /Продолжить ответ/ });
      expect(links.length).toBeGreaterThan(0);
      for (const link of links) {
        expect(link).toHaveAttribute("href", `/eds/new?draft=${documentId(950)}`);
      }
    });

    it("зарегистрирован, но не ушёл адресату: метка «Не отправлено» и причина словами; ссылка на карточку ИСХ", async () => {
      inExecution({ instructions: [replyInstruction()] });
      seedReply(
        { status: "sent", number: "ИСХ-014/26" },
        {
          id: "m-1",
          to: ["gni@example.uz"],
          status: "failed",
          reason: "Почта не настроена — Настройки · Подключения · Почта",
          requested_by: { crm_user_id: 4, full_name: "Демо Канцелярова" },
          requested_at: "2026-11-02T06:00:00Z",
          finished_at: "2026-11-02T06:01:00Z",
        },
      );
      signIn("universal@demo.example");
      renderAt(PATH);
      const block = await screen.findByRole("heading", { level: 2, name: "Ответ на письмо" });
      const card = block.closest(".ant-card") as HTMLElement;
      expect(within(card).getByText("Не отправлено")).toBeVisible();
      expect(
        within(card).getByText(/ИСХ-014\/26 не ушёл адресату: Почта не настроена/),
      ).toBeVisible();
      expect(within(card).getByRole("link", { name: /Открыть/ })).toHaveAttribute(
        "href",
        `/eds/documents?scope=all&doc=${documentId(950)}&panel=open`,
      );
    });

    it("«Исполнено» с ИСХ другого письма — понятный отказ, поручение остаётся в работе", async () => {
      inExecution({ instructions: [replyInstruction()] });
      seedReply({ status: "sent", number: "ИСХ-014/26", replyTo: "ВХ-90/26" });
      signIn("universal@demo.example");
      renderAt(PATH);
      const form = await screen.findByRole("form", { name: "Отметить исполнение" });
      fireEvent.change(within(form).getByLabelText(/Ответ — номер нашего ИСХ/), {
        target: { value: "ИСХ-014/26" },
      });
      fireEvent.click(within(form).getByRole("button", { name: "Исполнено" }));
      expect(await within(form).findByText(/уже отвечает на другое входящее письмо/)).toBeVisible();
      expect(findLetter("ВХ-108/26")?.instructions?.[0]?.status).toBe("in_work");
    });

    it("«Задачи» делопроизводителя: «Зарегистрировать ИСХ» — пока ответ передан и не зарегистрирован", () => {
      inExecution({ instructions: [replyInstruction()] });
      seedReply({
        letter: {
          body: null,
          recipient_attention: null,
          recipient_email: null,
          signatory_name: null,
          signatory_position: null,
          pdf: null,
          pdfPolls: 0,
          mailings: [],
          registration_requested: { ownerId: "u-demo-universal", at: "2026-11-02T05:30:00Z" },
        },
      });
      const rows = (email: string) => {
        signIn(email);
        const session = readSession();
        const roles = session ? sessionRoles(session) : undefined;
        return letterTaskQueueItems(roles?.view ?? []);
      };
      const [row] = rows("registrar@demo.example").filter((r) => r.kind === "register_reply");
      expect(row?.title).toBe("Зарегистрировать ИСХ: ответ на ВХ-108/26");
      expect(row?.object.path).toBe(`/eds/documents?scope=all&doc=${documentId(950)}&panel=open`);
      expect(rows("universal@demo.example").filter((r) => r.kind === "register_reply")).toEqual([]);
      const state = readEds();
      const doc = state.documents.find((d) => d.id === documentId(950));
      if (doc) doc.status = "sent";
      writeEds(state);
      expect(rows("registrar@demo.example").filter((r) => r.kind === "register_reply")).toEqual([]);
    });
  });
});

describe("Исходы письма (решение владельца 2026-11-11)", () => {
  it("ответственный закрывает без ответа: причина из справочника, пояснение обязательно, если причина требует", async () => {
    inExecution();
    signIn("universal@demo.example");
    renderAt(PATH);
    fireEvent.click(await screen.findByRole("button", { name: "Ещё" }));
    fireEvent.click(await screen.findByText("Закрыть без ответа"));
    const dialog = await screen.findByRole("dialog", { name: "ВХ-108/26: закрыть без ответа" });
    await chooseOption(within(dialog).getByLabelText("Причина"), "Недобросовестный контрагент");
    const submit = within(dialog).getByRole("button", { name: "Закрыть" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Пояснение (обязательно)"), {
      target: { value: "Срывал поставки" },
    });
    fireEvent.click(submit);
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.status).toBe("closed");
    });
    expect(findLetter("ВХ-108/26")?.close_comment).toBe("Срывал поставки");
    expect(
      await screen.findByText("Закрыто без ответа: Недобросовестный контрагент"),
    ).toBeVisible();
  });

  it("автор резолюции возвращает закрытое письмо в работу", async () => {
    inExecution({
      status: "closed",
      close_reason: "advertising",
      close_comment: null,
      executed_at: "2026-11-02T05:00:00Z",
      instructions: [
        instruction({ status: "executed", executed_at: "2026-11-02T05:00:00Z", report: "Закрыто" }),
      ],
    });
    signIn("director@demo.example");
    renderAt(PATH);
    expect(await screen.findByText("Закрыто без ответа: Реклама или рассылка")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Вернуть в работу" }));
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.status).toBe("in_execution");
    });
    expect(findLetter("ВХ-108/26")?.instructions?.[0]?.status).toBe("in_work");
  });

  it("ответственный возвращает письмо автору резолюции с причиной", async () => {
    inExecution();
    signIn("universal@demo.example");
    renderAt(PATH);
    fireEvent.click(await screen.findByRole("button", { name: "Ещё" }));
    fireEvent.click(await screen.findByText("Вернуть автору резолюции"));
    const dialog = await screen.findByRole("dialog", {
      name: "ВХ-108/26: вернуть автору резолюции",
    });
    fireEvent.change(within(dialog).getByLabelText("Причина"), {
      target: { value: "Это вопрос бухгалтерии" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Вернуть" }));
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.status).toBe("awaiting_resolution");
    });
    expect(findLetter("ВХ-108/26")?.instructions).toEqual([]);
  });
});
