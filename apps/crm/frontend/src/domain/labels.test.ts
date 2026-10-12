import { describe, expect, it } from "vitest";

import {
  auditActionLabel,
  decisionErrorLabel,
  entityLabel,
  languageLabel,
  looksLikeCode,
  qualificationText,
  reasonLabel,
  rejectedReason,
  segmentLabel,
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
    [
      "price_or_contract_asked, qualifier_recommend",
      "Цена/условия — нет в базе; Рекомендация квалификатора",
    ],
    ["complaint", "Жалоба"],
    ["human_requested, brand_new_trigger", "Просит человека; служебная причина"],
    ["qualifier: price_inquiry", "решение квалификатора"],
  ])("transition reason %s", (reason, expected) => {
    expect(transitionReason(reason)).toBe(expected);
  });

  // Тест-сторож (дизайн-аудит 2026-10-11, находка 2): в «Почему» не бывает snake_case-кодов.
  it.each([
    "price_or_contract_asked, qualifier_recommend",
    "human_requested",
    "kb_gap_streak, no_progress, high_score",
    "agent_unavailable",
    "some_future_code",
    "qualifier: request_contact",
    "taken by manager",
    "no reply for 14 days",
    "lead wrote again",
    "repeat deal",
  ])("transitionReason(%j) shows no raw codes", (reason) => {
    const text = transitionReason(reason);
    expect(text).not.toBe("");
    expect(text.split(/[;,:]\s*/).some((part) => looksLikeCode(part.trim()))).toBe(false);
    expect(text).not.toMatch(/[a-z]+_[a-z]+/);
  });

  it("hides technical rejection text", () => {
    expect(rejectedReason("transition won -> engaged is not allowed")).toBe("не применено");
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

describe("decisionErrorLabel", () => {
  it.each([
    ["LlmUnavailableError: qualifier-model", "ИИ-ассистент был недоступен — оценка не обновлена"],
    ["ValidationError: 1 validation error", "Ошибка квалификатора"],
    ["", "Ошибка квалификатора"],
  ])("%s", (error, expected) => {
    expect(decisionErrorLabel(error)).toBe(expected);
  });
});

describe("segmentLabel", () => {
  it.each([
    ["transport", "Транспорт"],
    ["Retail", "Ритейл"],
    ["агро", "Агро"],
    ["", "—"],
    [null, "—"],
  ])("%j → %s", (code, expected) => {
    expect(segmentLabel(code)).toBe(expected);
  });
});
