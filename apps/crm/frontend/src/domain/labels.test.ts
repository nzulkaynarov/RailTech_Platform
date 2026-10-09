import { describe, expect, it } from "vitest";

import {
  auditActionLabel,
  entityLabel,
  languageLabel,
  qualificationText,
  reasonLabel,
  rejectedReason,
  stageLabel,
  STAGE_ORDER,
  transitionReason,
} from "./labels";

describe("labels", () => {
  it.each([
    ["engaged", "Вовлечён", "blue"],
    ["unresponsive", "Не отвечает", "default"],
    ["customer", "Клиент", "cyan"],
    ["mystery", "mystery", "default"],
  ])("stage %s", (code, label, color) => {
    expect(stageLabel(code)).toEqual({ label, color });
  });

  it("covers every stage in the funnel order", () => {
    expect(STAGE_ORDER.every((s) => stageLabel(s).label !== s)).toBe(true);
  });

  it.each([
    ["taken by manager", "менеджер забрал лида"],
    ["no reply for 7 days", "нет ответа 7 дн."],
    ["qualifier: уточнить сроки", "квалификатор: уточнить сроки"],
    ["Клиент передумал", "Клиент передумал"],
    [null, ""],
  ])("transition reason %s", (reason, expected) => {
    expect(transitionReason(reason)).toBe(expected);
  });

  it("hides technical rejection text", () => {
    expect(rejectedReason("transition won -> engaged is not allowed")).toBe(
      "переход не разрешён правилами",
    );
  });

  it.each([
    ["timeline", "<3m", "Срок: до 3 мес."],
    ["decision_role", "decision_maker", "Роль: ЛПР"],
    ["company", "ООО Альфа", "Компания: ООО Альфа"],
  ])("qualification %s=%s", (key, value, expected) => {
    expect(qualificationText(key, value)).toBe(expected);
  });

  it("translates audit, entities, languages and reasons", () => {
    expect(auditActionLabel("settings.update")).toBe("Изменил настройки");
    expect(entityLabel("kb_gap")).toBe("Пробел базы знаний");
    expect(languageLabel("UZ")).toBe("UZ");
    expect(reasonLabel("agent_unavailable")).toBe("Сбой ИИ-ассистента");
  });
});
