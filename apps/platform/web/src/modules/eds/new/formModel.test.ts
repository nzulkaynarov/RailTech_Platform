import { describe, expect, it } from "vitest";

import {
  EMPTY_FORM,
  type FormValues,
  consequenceKey,
  fromDocument,
  kindFromParam,
  parseAmount,
  routeKind,
  todayInCompanyZone,
  toCreateBody,
  toUpdateBody,
  validate,
} from "./formModel";

const FILLED: FormValues = { ...EMPTY_FORM, subject: "Закупка", text: "Прошу согласовать." };

describe("formModel", () => {
  it("тип из адреса: statement -> заявление, letter -> письмо, остальное — служебная записка", () => {
    expect(kindFromParam("memo")).toBe("memo");
    expect(kindFromParam("statement")).toBe("application");
    expect(kindFromParam("report")).toBe("report");
    expect(kindFromParam("letter")).toBe("letter_out");
    expect(kindFromParam("contract")).toBe("memo");
    expect(kindFromParam(null)).toBe("memo");
  });

  it("сумма из поля: пробелы разрядов, запятая, два знака; нуль и мусор — ошибка; пусто — суммы нет", () => {
    expect(parseAmount("")).toEqual({ ok: true, value: null });
    expect(parseAmount("  ")).toEqual({ ok: true, value: null });
    expect(parseAmount("1 500 000")).toEqual({ ok: true, value: "1500000.00" });
    expect(parseAmount("1 500 000,5")).toEqual({ ok: true, value: "1500000.50" });
    expect(parseAmount("2500.75")).toEqual({ ok: true, value: "2500.75" });
    expect(parseAmount("007")).toEqual({ ok: true, value: "7.00" });
    for (const bad of ["0", "0,00", "-5", "12,345", "abc", "1e6"]) {
      expect(parseAmount(bad), bad).toEqual({ ok: false });
    }
  });

  it("обязательны тема и текст; сумма больше нуля; «нужно до» не в прошлом", () => {
    expect(validate(EMPTY_FORM, "2026-10-27")).toEqual({ subject: true, text: true });
    expect(validate({ ...FILLED, amount: "0" }, "2026-10-27")).toEqual({ amount: true });
    expect(validate({ ...FILLED, dueDate: "2026-10-26" }, "2026-10-27")).toEqual({
      due_date: true,
    });
    expect(validate({ ...FILLED, dueDate: "2026-10-27" }, "2026-10-27")).toEqual({});
    expect(
      validate({ ...FILLED, amount: "1 500 000", dueDate: "2026-11-05" }, "2026-10-27"),
    ).toEqual({});
  });

  it("у письма обязателен адресат, а сумма и срок не проверяются", () => {
    const letter: FormValues = {
      ...FILLED,
      kind: "letter_out",
      amount: "0",
      dueDate: "2020-01-01",
    };
    expect(validate(letter, "2026-10-27")).toEqual({ recipient: true });
    expect(validate({ ...letter, recipientName: "ООО «Пример»" }, "2026-10-27")).toEqual({});
  });

  it("тело запроса: деньги строкой с двумя знаками, пустое — null, письмо несёт адресата и не несёт сумму", () => {
    const form: FormValues = {
      ...FILLED,
      subject: "  Закупка  ",
      amount: "1 500 000",
      dueDate: "2026-11-05",
      deal: { erp_deal_id: 904, label: "ЗВ-2026-104" },
      attachments: [
        { key: "a", name: "a.pdf", size: 1, status: "done", id: "f-1" },
        { key: "b", name: "b.pdf", size: 1, status: "uploading" },
        { key: "c", name: "c.pdf", size: 1, status: "error", error: "x" },
      ],
    };
    expect(toCreateBody(form, true)).toEqual({
      kind: "memo",
      subject: "Закупка",
      text: "Прошу согласовать.",
      amount: { amount: "1500000.00", currency: "UZS" },
      due_date: "2026-11-05",
      file_ids: ["f-1"],
      erp_deal_id: 904,
      submit: true,
    });
    expect(toUpdateBody(FILLED, false)).toEqual({
      subject: "Закупка",
      text: "Прошу согласовать.",
      amount: null,
      due_date: null,
      file_ids: [],
      erp_deal_id: null,
      submit: false,
    });
    const letter = toCreateBody(
      {
        ...FILLED,
        kind: "letter_out",
        amount: "500",
        recipientName: " ООО «Пример» ",
        recipientInn: "",
      },
      true,
    );
    expect(letter).toMatchObject({
      kind: "letter_out",
      amount: null,
      due_date: null,
      recipient: { name: "ООО «Пример»", inn: null },
    });
  });

  it("маршрут и «Что произойдёт»: с суммой служебка идёт ещё и бухгалтеру; у заявления и отчёта сумма маршрут не меняет", () => {
    expect(routeKind(FILLED)).toBe("plain");
    expect(consequenceKey(FILLED)).toBe("memo");
    expect(routeKind({ ...FILLED, amount: "100" })).toBe("withAmount");
    expect(consequenceKey({ ...FILLED, amount: "100" })).toBe("memoAmount");
    expect(routeKind({ ...FILLED, kind: "application", amount: "100" })).toBe("plain");
    expect(consequenceKey({ ...FILLED, kind: "report" })).toBe("report");
    expect(routeKind({ ...FILLED, kind: "letter_out" })).toBe("letter");
    expect(consequenceKey({ ...FILLED, kind: "letter_out" })).toBe("letter");
  });

  it("сегодня — по часовому поясу компании: в 23:30 UTC в Ташкенте уже следующий день", () => {
    expect(todayInCompanyZone(new Date("2026-10-27T23:30:00Z"))).toBe("2026-10-28");
    expect(todayInCompanyZone(new Date("2026-10-27T10:00:00Z"))).toBe("2026-10-27");
  });

  it("черновик -> форма: сумма без «.00», вложения закреплены, связь с проектом подписана номером", () => {
    const values = fromDocument({
      id: "d-1",
      kind: "memo",
      number: "СЗ-2026/033",
      status: "draft",
      version: 1,
      subject: "Ремонт",
      text: "Нужно заменить компрессор.",
      author: { crm_user_id: 1, full_name: "Демо Менеджеров" },
      addressee: null,
      amount: { amount: "1200000.00", currency: "UZS" },
      due_date: "2026-11-05",
      files: [{ id: "f-1", name: "schet.pdf", content_type: "application/pdf", size: 10 }],
      deal: { erp_deal_id: 904, number: "ЗВ-2026-104" },
      recipient: null,
      route: [],
      decisions: [],
      can_edit: true,
      created_at: "2026-10-27T07:45:00Z",
      updated_at: "2026-10-27T07:45:00Z",
    });
    expect(values.amount).toBe("1200000");
    expect(values.dueDate).toBe("2026-11-05");
    expect(values.deal).toEqual({ erp_deal_id: 904, label: "ЗВ-2026-104" });
    expect(values.attachments).toEqual([
      { key: "f-1", name: "schet.pdf", size: 10, status: "done", id: "f-1", existing: true },
    ]);
  });
});
