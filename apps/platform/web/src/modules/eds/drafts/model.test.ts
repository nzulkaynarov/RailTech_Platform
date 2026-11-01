import { describe, expect, it } from "vitest";

import type { QuoteChecklistLine } from "../../../shared/api/generated/model";
import { channelStates, defaultChannels, lateWarning, redBlockers } from "./model";

function line(
  code: QuoteChecklistLine["code"],
  ok: boolean,
  blocking = code !== "due",
): QuoteChecklistLine {
  return { code, ok, blocking, by_name: null, at: null };
}

describe("чек-лист одобрения КП", () => {
  it("блокируют красные визы и маржа; красный срок — не блок", () => {
    const checklist = [
      line("visa_goods", true),
      line("visa_services", false),
      line("margin", false),
      line("due", false),
    ];
    expect(redBlockers(checklist)).toEqual(["visa_services", "margin"]);
    expect(lateWarning(checklist)?.code).toBe("due");
  });

  it("всё зелёное — блокировок и предупреждения нет", () => {
    const checklist = [line("visa_goods", true), line("margin", true), line("due", true)];
    expect(redBlockers(checklist)).toEqual([]);
    expect(lateWarning(checklist)).toBeNull();
  });
});

describe("каналы отправки клиенту", () => {
  it("недоступному каналу — причина словарным ключом; по умолчанию отмечены доступные", () => {
    const states = channelStates({
      contact_name: "Алия Демо",
      telegram: true,
      cabinet: false,
      email: false,
      reasons: { telegram: null, cabinet: "no_cabinet", email: "mail_not_configured" },
    });
    expect(states).toEqual([
      { channel: "telegram", available: true, reason: null },
      { channel: "cabinet", available: false, reason: "no_cabinet" },
      { channel: "email", available: false, reason: "mail_not_configured" },
    ]);
    expect(defaultChannels(states)).toEqual(["telegram"]);
  });

  it("ERP не ответила — все каналы выбираемы", () => {
    const states = channelStates(null);
    expect(states.every((s) => s.available && s.reason === null)).toBe(true);
    expect(defaultChannels(states)).toEqual(["telegram", "cabinet", "email"]);
  });
});
