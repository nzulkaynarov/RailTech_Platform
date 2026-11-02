import { describe, expect, it } from "vitest";

import { ApiError } from "../../../shared/api/errors";
import type { InboundMail } from "../../../shared/api/generated/model";
import { arrivedAt, canReturn, inWorkByOther, prefillFromMail, statusKey } from "./mailModel";

function mail(over: Partial<InboundMail> = {}): InboundMail {
  return {
    id: 5,
    status: "new",
    from_email: "a@b.example",
    from_name: "",
    subject: "Счёт",
    received_at: "2026-11-01T20:30:00Z",
    sent_at: null,
    activity_at: "2026-11-01T20:30:00Z",
    preview: "",
    attachments_count: 0,
    assist: { status: "done", kind: "official", summary: "Письмо банка", action: "register" },
    client: null,
    lead: null,
    from_history: false,
    assignee: null,
    assigned_at: null,
    personal: false,
    thread_reply: false,
    unread: true,
    messages_count: 1,
    eds_waiting: false,
    result: null,
    to: [],
    cc: [],
    text: "Текст",
    attachments: [],
    skipped: [],
    too_large: false,
    inns: ["301234567"],
    messages: [],
    replies: [],
    journal: [],
    reply_all_copy: [],
    personal_label: "Адресовано лично",
    ...over,
  };
}

describe("arrivedAt", () => {
  it("у письма «из истории» — дата письма, у обычного — когда пришло в ящик", () => {
    const m = { sent_at: "2026-10-01T05:00:00Z", received_at: "2026-11-03T05:00:00Z" };
    expect(arrivedAt({ ...m, from_history: true })).toBe("2026-10-01T05:00:00Z");
    expect(arrivedAt({ ...m, from_history: false })).toBe("2026-11-03T05:00:00Z");
    expect(arrivedAt({ ...m, sent_at: null, from_history: true })).toBe("2026-11-03T05:00:00Z");
  });
});

describe("prefillFromMail", () => {
  it("переносит корреспондента, дату, суть, вложения и источник; вид — только однозначный", () => {
    expect(prefillFromMail(mail(), [])).toMatchObject({
      kind: "",
      receiptMethod: "email",
      senderName: "a@b.example",
      senderInn: "301234567",
      receivedAt: "2026-11-02",
      summary: "Письмо банка",
      sourceMailId: 5,
      attachments: [],
    });
  });

  it("адресат — сотрудник из «Кому», «ознакомить» — сотрудники из копии (кроме адресата)", () => {
    const boss = { id: 11, name: "Иванов" };
    const values = prefillFromMail(
      mail({
        to: [
          { email: "client@x.example", staff: null, mailbox: false },
          { email: "boss@x.example", staff: boss, mailbox: false },
        ],
        cc: [
          { email: "info@x.example", staff: null, mailbox: true },
          { email: "boss@x.example", staff: boss, mailbox: false },
          { email: "p@x.example", staff: { id: 12, name: "Петров" }, mailbox: false },
        ],
      }),
      [],
    );
    expect(values).toMatchObject({
      addresseeId: "11",
      draftKind: "info",
      draftAcquaintIds: ["12"],
    });
  });

  it("нет сотрудников — адресата и проекта резолюции не выдумывает", () => {
    const values = prefillFromMail(mail(), []);
    expect(values).not.toHaveProperty("addresseeId");
    expect(values).not.toHaveProperty("draftKind");
  });
});

describe("inWorkByOther", () => {
  it("узнаёт 409 «уже в работе у …» и достаёт имя и время", () => {
    const error = new ApiError(409, "CONFLICT", "x", "crm", {
      reason: "mail_in_work_by_other",
      assignee_name: "Иванов",
      assigned_at: "2026-11-03T05:42:00Z",
    });
    expect(inWorkByOther(error)).toEqual({ name: "Иванов", since: "2026-11-03T05:42:00Z" });
  });

  it.each([
    new ApiError(409, "CONFLICT", "x", "crm", { reason: "mail_handled" }),
    new ApiError(403, "FORBIDDEN", "x", "crm", { reason: "mail_in_work_by_other" }),
    new Error("boom"),
  ])("остальное — не «в работе у другого»", (error) => {
    expect(inWorkByOther(error)).toBeNull();
  });
});

describe("canReturn и statusKey", () => {
  it.each([
    ["done", "archived", true],
    ["done", "replied", true],
    ["done", "registered", false],
    ["done", "lead", false],
    ["new", null, false],
  ] as const)("%s/%s → вернуть можно: %s", (status, outcome, expected) => {
    const result = outcome
      ? {
          outcome,
          by: null,
          at: null,
          letter_number: null,
          letter_ref: null,
          lead: null,
          reason: null,
        }
      : null;
    expect(canReturn({ status, result })).toBe(expected);
  });

  it("«Новое · ответ в цепочке» только у нового с признаком цепочки", () => {
    expect(statusKey({ status: "new", thread_reply: true })).toBe("mail.status.newReply");
    expect(statusKey({ status: "new", thread_reply: false })).toBe("mail.status.new");
    expect(statusKey({ status: "in_work", thread_reply: true })).toBe("mail.status.in_work");
  });
});
