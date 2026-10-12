import { describe, expect, it } from "vitest";

import type { AuditItem } from "../api/generated/model";
import { type AuditContext, auditChanges, auditDiff, entityText, fieldName } from "./audit";
import { ownerModeLabel, stageLabel } from "./labels";

const ctx: AuditContext = {
  userName: (id) => ({ 1: "Анна", 2: "Бахтиёр" })[id],
  productName: (key) => ({ "rail-tracking": "RT-Track" })[key],
};

const item = (before: object | null, after: object | null): AuditItem =>
  ({
    id: 1,
    action: "x",
    actor_type: "user",
    actor_user_id: 1,
    entity_type: "lead",
    entity_id: "1",
    created_at: "2026-10-11T10:00:00Z",
    ip: null,
    before,
    after,
  }) as unknown as AuditItem;

/** Записи, которые реально пишет бэкенд (services/*: audit.record before/after). */
const BACKEND_SAMPLES: [string, AuditItem, string][] = [
  [
    "lead take",
    item(
      { stage: "handoff", owner_mode: "paused", assigned_user_id: null },
      { stage: "in_progress", owner_mode: "human", assigned_user_id: 1 },
    ),
    // Метки стадий/режимов — из словаря (Q-015 может их переименовать).
    `Стадия: ${stageLabel("handoff").label} → ${stageLabel("in_progress").label}; ` +
      `Кто ведёт: ${ownerModeLabel("paused")} → ${ownerModeLabel("human")}; Ответственный: — → Анна`,
  ],
  ["lead note", item(null, { note_id: 7, visible_to_bot: true }), "Заметка: #7; Бот учитывает: Да"],
  [
    "user create",
    item(null, {
      email: "a@b.uz",
      full_name: "Анна",
      roles: ["viewer"],
      is_active: true,
      tg_user_id: null,
    }),
    "Email: a@b.uz; Имя: Анна; Роли: Наблюдатель; Активен: Да; Telegram ID: —",
  ],
  [
    "hand over",
    item(null, { to_user_id: 2, active_leads: 3 }),
    "Кому передано: Бахтиёр; Лидов передано: 3",
  ],
  ["make customer", item(null, { client_id: 4 }), "Клиент: Клиент #4"],
  [
    "kb upload",
    item(null, { title: "Прайс", language: "ru", product: "rail-tracking" }),
    "Название: Прайс; Язык: RU; Продукт: RT-Track",
  ],
  [
    "document update",
    item({ is_visible_to_client: "False" }, { is_visible_to_client: "True" }),
    "Виден клиенту: Нет → Да",
  ],
  [
    "client update",
    item({ owner_user_id: null, segment: "transport" }, { owner_user_id: 2, segment: "retail" }),
    "Ответственный: — → Бахтиёр; Сегмент: transport → retail",
  ],
  [
    "settings texts",
    item(
      { greeting: { ru: "Привет", uz: "Salom", en: "Hi" } },
      { greeting: { ru: "Здравствуйте", uz: "Salom", en: "Hi" } },
    ),
    "Приветствие (RU): Привет → Здравствуйте",
  ],
  [
    "settings hours",
    item({ weekdays: [0, 1, 2, 3, 4] }, { weekdays: [0, 1, 2, 3, 4, 5] }),
    "Рабочие дни: Пн, Вт, Ср, Чт, Пт → Пн, Вт, Ср, Чт, Пт, Сб",
  ],
  [
    "lead assist",
    item(null, { mode: "draft", input_chars: 0, output_chars: 120, notice: null }),
    "Режим: черновик; Символов в запросе: 0; Символов в ответе: 120; Предупреждение: —",
  ],
  [
    "deal lost",
    {
      ...item(
        { stage: "open", amount: null, lost_reason: null },
        { stage: "lost", amount: "1500.00", lost_reason: "Дорого" },
      ),
      entity_type: "deal",
    },
    "Стадия: Открыта → Проиграна; Сумма: — → 1500.00; Причина отказа: — → Дорого",
  ],
  [
    "contact create",
    item(null, { contact_id: 3, phone_e164: "+998901234567", is_primary: true, position: "ГД" }),
    "Контакт: #3; Телефон: +998901234567; Основной контакт: Да; Должность: ГД",
  ],
  [
    "model update",
    item({ models: ["a"] }, { model: "b", api_base: null, key: "env" }),
    "Модели: a → —; Модель: b; Адрес API: —; Ключ API: из переменных сервера",
  ],
  [
    "user notify",
    item({ notify_system: true, notify_leads: false }, { notify_system: true, notify_leads: true }),
    "Уведомления о лидах: Нет → Да",
  ],
];

describe("audit diff", () => {
  it.each(BACKEND_SAMPLES)("%s", (_name, entry, expected) => {
    expect(auditDiff(entry, ctx)).toBe(expected);
  });

  it("guard: no raw snake_case keys or codes in any sample", () => {
    for (const [, entry] of BACKEND_SAMPLES) {
      expect(auditDiff(entry, ctx)).not.toMatch(/\b[a-z]+_[a-z_]+\b/);
    }
  });

  it("shows only changed fields", () => {
    expect(
      auditChanges(
        item({ stage: "new", owner_mode: "bot" }, { stage: "new", owner_mode: "human" }),
        ctx,
      ),
    ).toEqual([
      { field: "Кто ведёт", before: ownerModeLabel("bot"), after: ownerModeLabel("human") },
    ]);
  });

  it("unknown user id falls back to #id", () => {
    expect(auditDiff(item(null, { assigned_user_id: 99 }), ctx)).toBe("Ответственный: #99");
  });

  it("settings field names come from settings labels", () => {
    expect(fieldName("high_score_threshold")).toBe("Оценка лида для передачи");
  });
});

describe("system records in human words", () => {
  it("model test: role name and cost below a cent", () => {
    const changes = auditChanges(item(null, { ok: true, cost_usd: 0.0003 }), ctx);
    expect(changes).toEqual([
      { field: "Ответила", after: "Да" },
      { field: "Стоимость", after: "< $0.01" },
    ]);
    expect(entityText("model", "dialog-model", ctx)).toBe("Модель ИИ «Диалог»");
  });

  it("objects without a card get a human name", () => {
    expect(entityText("system", "backups", ctx)).toBe("Резервные копии");
    expect(entityText("export", "deals", ctx)).toBe("Выгрузка сделок");
    expect(entityText("integration_secret", "telegram_bot_token", ctx)).toBe("Токен Telegram-бота");
    expect(entityText("sandbox", "1", ctx)).toBe("Проверить бота");
    expect(entityText("deal", "4", ctx)).toBeUndefined();
  });

  it("user entity shows the name", () => {
    expect(entityText("user", "2", ctx)).toContain("Бахтиёр");
    expect(entityText("lead", "2", ctx)).toBeUndefined();
  });
});
