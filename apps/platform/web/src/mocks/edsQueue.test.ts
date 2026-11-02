import { beforeEach, describe, expect, it } from "vitest";

import { edsDecisionQueueItems, quoteCounter, quotesToApprove } from "./edsQueue";
import {
  readMemos,
  readQuotes,
  resetApprovals,
  writeMemos,
  writeQuotes,
} from "./fixtures/approvals";
import { seedRoles } from "./fixtures/roles";

const role = (code: string) => {
  const found = seedRoles().find((r) => r.code === code || r.code === `tpl:${code}`);
  if (!found) throw new Error(`нет роли ${code}`);
  return found;
};

beforeEach(() => {
  resetApprovals();
});

describe("моки «Моих задач»: решения EDS из складов «КП на одобрение» и «На согласовании»", () => {
  it("директор: строка «Одобрить КП» на каждое КП на его шаге; карточка и бейдж — то же число (D26G-4)", () => {
    const view = [role("DIRECTOR")];
    const open = readQuotes().filter((q) => q.status === "open" && q.can_decide);
    const rows = edsDecisionQueueItems(view).filter((i) => i.kind === "approve_quote");

    expect(rows.map((r) => r.title)).toEqual(open.map((q) => `Одобрить ${q.number}`));
    expect(quotesToApprove(view)).toBe(rows.length);
    expect(quoteCounter(view)).toEqual([
      { module: "eds", section: "drafts", count: rows.length, attention: true },
    ]);
  });

  it("КП одобрено на экране — строка уходит, число уменьшается", () => {
    const view = [role("DIRECTOR")];
    const before = quotesToApprove(view) ?? 0;
    const [first, ...rest] = readQuotes();
    if (!first) throw new Error("нет КП");
    writeQuotes([{ ...first, status: "approved", can_decide: false }, ...rest]);

    expect(quotesToApprove(view)).toBe(before - 1);
    expect(edsDecisionQueueItems(view).some((i) => i.object.number === first.number)).toBe(false);
  });

  it("менеджер-универсал: «Принять к оплате» на шаге «Бухгалтер», «Одобрить КП» — нет (D26G-9)", () => {
    const view = [role("MANAGER_ALL")];
    const rows = edsDecisionQueueItems(view);

    expect(rows.map((r) => [r.kind, r.object.number])).toEqual([["pay_memo", "СЗ-2026/015"]]);
    expect(quotesToApprove(view)).toBeNull();

    writeMemos(
      readMemos().map((m) => (m.number === "СЗ-2026/015" ? { ...m, status: "approved" } : m)),
    );
    expect(edsDecisionQueueItems(view)).toEqual([]);
  });
});
