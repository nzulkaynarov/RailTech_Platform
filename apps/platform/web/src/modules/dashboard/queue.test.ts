import { describe, expect, it } from "vitest";

import i18n from "../../shared/i18n";
import type { Me, QueueItem } from "../../shared/api/generated/model";
import { isUrgent, queueEmptyKind } from "./queue";
import {
  acquaintLetterId,
  actionKeyOf,
  ageOf,
  canRemind,
  chipsOf,
  groupOf,
  groupsOf,
  quickActionOf,
} from "./queueModel";

const me = (resources: Record<string, "read" | "full">): Me =>
  ({ resources, modules: [], roles: [] }) as unknown as Me;

describe("queueEmptyKind: пустое состояние — по разделам каталога, не по кодам ролей", () => {
  it.each([
    ["письма и резолюции", { "eds.inbox": "full" }, "director"],
    ["одобрение КП", { "eds.drafts": "full", "eds.payments": "full" }, "director"],
    ["согласование служебок", { "eds.memo.approve": "full" }, "director"],
    [
      "продажи, расчёт, счета и оплаты (менеджер-универсал)",
      { "crm.leads": "full", "erp.calc": "full", "eds.payments": "full", "eds.inbox": "read" },
      "universal",
    ],
    ["платёжки", { "eds.payments": "full", "erp.calc": "read" }, "accountant"],
    ["виза товаров и склада", { "erp.calc.goods": "full", "erp.stock": "full" }, "supply"],
    ["виза услуг", { "erp.calc.services": "full", "erp.stock": "full" }, "engineer"],
    ["лиды", { "crm.leads": "full", "eds.inbox": "read" }, "manager"],
    ["настройки", { admin: "full" }, "admin"],
    ["только чтение", { "crm.leads": "read", "eds.payments": "read" }, "default"],
    ["ничего", {}, "default"],
  ] as const)("%s → %s", (_name, resources, expected) => {
    expect(queueEmptyKind(me({ ...resources }))).toBe(expected);
  });
});

describe("isUrgent: primary у «сегодня» и «просрочено»", () => {
  it.each([
    ["overdue", true],
    ["today", true],
    ["tomorrow", false],
    ["later", false],
    ["memo", false],
  ] as const)("%s → %s", (label, expected) => {
    expect(isUrgent({ due_label: label })).toBe(expected);
  });
});

describe("«Что ждёт вас»: группы, чипы, быстрые действия (ГЛ-1)", () => {
  const item = (over: Partial<QueueItem>): QueueItem => ({
    id: "x",
    role_id: "1",
    kind: "approve_memo",
    title: "t",
    subtitle: "",
    due_label: "later",
    object: { kind: "memo", number: "СЗ-1", path: "/eds/approvals/СЗ-1" },
    ...over,
  });

  it("группа берётся у BFF; без неё — из срока: просрочено, сегодня, остальное «позже»", () => {
    expect(groupOf(item({ group: "today", due_label: "later" }))).toBe("today");
    expect(groupOf(item({ due_label: "overdue" }))).toBe("overdue");
    expect(groupOf(item({ due_label: "today" }))).toBe("today");
    expect(groupOf(item({ due_label: "tomorrow" }))).toBe("later");
    expect(groupOf(item({ due_label: "memo" }))).toBe("later");
  });

  it("чипы: счётчик каждого вида = число его строк; пустых видов нет; порядок — решения первыми", () => {
    const chips = chipsOf([
      item({ category: "lead" }),
      item({ category: "sign" }),
      item({ category: "sign" }),
      item({}),
    ]);
    expect(chips).toEqual([
      { category: "sign", count: 2 },
      { category: "lead", count: 1 },
      { category: "other", count: 1 },
    ]);
  });

  it("группы: пустые не показываются, порядок просрочено → сегодня → позже", () => {
    const blocks = groupsOf([
      item({ id: "a", group: "later" }),
      item({ id: "b", group: "overdue" }),
      item({ id: "c", group: "later" }),
    ]);
    expect(blocks.map((b) => [b.group, b.items.map((i) => i.id)])).toEqual([
      ["overdue", ["b"]],
      ["later", ["a", "c"]],
    ]);
  });

  it("быстрое действие — только «Ознакомлен» и «Взять», и не у строки «за {имя}»", () => {
    expect(quickActionOf(item({ kind: "acquaint" }))).toBe("acknowledge");
    expect(quickActionOf(item({ kind: "take_lead" }))).toBe("take");
    expect(quickActionOf(item({ kind: "sign_document" }))).toBeNull();
    expect(quickActionOf(item({ kind: "answer_lead" }))).toBeNull();
    expect(
      quickActionOf(item({ kind: "acquaint", on_behalf_of: { id: "12", name: "Мадина" } })),
    ).toBeNull();
    expect(acquaintLetterId("acquaint:abc")).toBe("abc");
  });

  it("«ждёт»: минуты, часы, дни; «Напомнить» — когда можно и срок после прошлого вышел", () => {
    const now = Date.parse("2027-01-15T08:00:00Z");
    expect(ageOf("2027-01-15T07:20:00Z", now)).toEqual({ unit: "minutes", count: 40 });
    expect(ageOf("2027-01-15T05:00:00Z", now)).toEqual({ unit: "hours", count: 3 });
    expect(ageOf("2027-01-13T08:00:00Z", now)).toEqual({ unit: "days", count: 2 });
    expect(canRemind({ remindable: true }, now)).toBe(true);
    expect(canRemind({ remindable: false }, now)).toBe(false);
    expect(canRemind({ remindable: true, remind_available_at: "2027-01-15T09:00:00Z" }, now)).toBe(
      false,
    );
    expect(canRemind({ remindable: true, remind_available_at: "2027-01-15T07:00:00Z" }, now)).toBe(
      true,
    );
  });
});

describe("actionKeyOf: подпись кнопки строки — из i18n по виду, не из русского глагола BFF", () => {
  it("виза отличается от подписи категорией, ответ по поручению — глаголом", () => {
    expect(
      actionKeyOf({ kind: "sign_document", category: "sign", action_label: "Подписать" }),
    ).toBe("sign_document");
    expect(actionKeyOf({ kind: "sign_document", category: "approve", action_label: "x" })).toBe(
      "visa",
    );
    expect(
      actionKeyOf({
        kind: "instruction",
        category: "instruction",
        action_label: "Подготовить ответ",
      }),
    ).toBe("instruction_reply");
  });

  it.each(["ru", "en", "uz"])("у каждого ключа есть текст на языке %s", async (lang) => {
    await i18n.changeLanguage(lang);
    const keys = [
      "sign_document",
      "visa",
      "acquaint",
      "take_lead",
      "instruction_reply",
      "ship_project",
    ];
    for (const key of keys) {
      expect(i18n.exists(`modules:dashboard.queue.actions.${key}`)).toBe(true);
    }
    const t = i18n.getFixedT(lang);
    expect(t("modules:dashboard.queue.actions.sign_document")).toBe(
      { ru: "Подписать", en: "Sign", uz: "Imzolaş" }[lang],
    );
    await i18n.changeLanguage("ru");
  });
});
