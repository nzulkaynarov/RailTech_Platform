import { describe, expect, it } from "vitest";

import type {
  AttentionItem,
  BrandProfile,
  FxRateOverview,
  SigningAuthority,
} from "../../../shared/api/generated/model";
import {
  blankRows,
  busLine,
  fxRows,
  ordered,
  readinessState,
  serviceRows,
  signingRows,
  ticketRows,
  zoneRows,
} from "./model";

/** «Состояние» (ЕВ-2а): строка «Требует внимания» выводится из факта — правим факт и ждём, что строка появится или уйдёт. */

const authority = (patch: Partial<SigningAuthority>): SigningAuthority =>
  ({
    id: "a1",
    holder: { id: "u1", name: "Рустам Каримов" },
    holder_active: true,
    status: "expiring",
    kinds: ["contract"],
    expires_in_days: 9,
    valid_to: "2026-12-02",
    basis_number: "14",
    ...patch,
  }) as SigningAuthority;

describe("полномочие подписи", () => {
  it("истекает через 9 дней — строка с именем и числом дней, исправляет администратор", () => {
    const [row] = signingRows([authority({})]);
    expect(row).toMatchObject({
      kind: "signing",
      owner: "admin",
      to: "/admin/signing",
      page: "signing",
      params: { name: "Рустам Каримов", days: 9, until: "2026-12-02" },
    });
  });

  it("действующее, отозванное, отключённого держателя и срок дальше 14 дней — строки нет", () => {
    expect(signingRows([authority({ status: "active", expires_in_days: 90 })])).toEqual([]);
    expect(signingRows([authority({ status: "revoked", expires_in_days: null })])).toEqual([]);
    expect(signingRows([authority({ holder_active: false })])).toEqual([]);
    // статус — тоже факт: не «истекающее» по версии сервера строки нет, сколько бы дней ни осталось
    expect(signingRows([authority({ status: "scheduled", expires_in_days: 5 })])).toEqual([]);
    expect(signingRows([authority({ expires_in_days: 15 })])).toEqual([]);
  });
});

describe("истёкшее полномочие подписи", () => {
  const expired = authority({
    id: "old",
    status: "expired",
    expires_in_days: null,
    valid_to: "2026-11-20",
  });

  it("срок вышел, преемника нет — строка не пропадает в день окончания срока, а краснеет", () => {
    // переход expiring → expired: строка осталась, стала сбоем
    expect(signingRows([authority({})])).toHaveLength(1);
    const [row] = signingRows([expired]);
    expect(row).toMatchObject({ kind: "signingExpired", severity: "fail", to: "/admin/signing" });
  });

  it("есть действующий преемник на те же виды подписи — строки нет; на другие виды — есть", () => {
    const successor = authority({ id: "new", status: "active", expires_in_days: 300 });
    expect(signingRows([expired, successor])).toEqual([]);
    expect(signingRows([expired, { ...successor, kinds: ["other"] }])).toHaveLength(1);
    // отключённый держатель преемником не считается
    expect(signingRows([expired, { ...successor, holder_active: false }])).toHaveLength(1);
  });

  it("истёкшее у отключённого держателя — строки нет", () => {
    expect(signingRows([{ ...expired, holder_active: false }])).toEqual([]);
  });
});

describe("кнопка к закрытой странице", () => {
  it("зрителю без права на страницу сервиса кнопки нет, строка остаётся", () => {
    const item = {
      id: "i1",
      card: "telegram",
      kind: "bot_not_running",
      group: null,
      severity: "fail",
    } as AttentionItem;
    const [closed] = serviceRows([item], () => false);
    expect(closed?.to).toBeNull();
    const [open] = serviceRows([item], () => true);
    expect(open?.to).toBe("/admin/telegram");
  });
});

describe("курс", () => {
  const fx = (current: FxRateOverview["current"]): FxRateOverview => ({
    currency: "USD",
    currencies: [],
    current,
    max_age_days: 3,
    journal: [],
    journal_available: false,
  });

  it("свежего курса нет (`current: null`) — строка, исправляет бухгалтер, ведёт в «Налоги и валюты»", () => {
    expect(fxRows(fx(null))).toMatchObject([
      { kind: "fx", owner: "accountant", to: "/admin/taxes", params: { currency: "USD", days: 3 } },
    ]);
  });

  it("курс есть или ответа ещё нет — строки нет", () => {
    expect(fxRows(fx({ rate_to_uzs: "12650", rate_date: "2026-11-23", source: "auto" }))).toEqual(
      [],
    );
    expect(fxRows(undefined)).toEqual([]);
  });
});

describe("бланк", () => {
  const brand = (logo_url: string | null) => ({ logo_url }) as BrandProfile;

  it("логотипа нет — «Не задан бланк», исправляет директор, ведёт к части «Бланк»", () => {
    expect(blankRows(brand(null))).toMatchObject([
      { kind: "blank", owner: "director", to: "/admin/company?part=brand" },
    ]);
  });

  it("логотип загружен — строки нет", () => {
    expect(blankRows(brand("/admin/company/brand/logo"))).toEqual([]);
  });
});

describe("службы", () => {
  const item = (patch: Partial<AttentionItem>): AttentionItem => ({
    id: "x",
    card: "mail",
    severity: "warn",
    kind: "service",
    subject: null,
    detail: null,
    group: null,
    technical: null,
    ...patch,
  });

  it("«ещё не подключено» — не сбой: в «Требует внимания» его нет, оно в готовности", () => {
    expect(serviceRows([item({ severity: "setup", kind: "not_configured" })])).toEqual([]);
  });

  it("сбой — красным, ведёт на свою страницу канала; сбои идут первыми", () => {
    const rows = ordered([
      ...serviceRows([item({ id: "w", card: "erp", severity: "warn" })]),
      ...serviceRows([item({ id: "f", card: "telegram", severity: "fail" })]),
    ]);
    expect(rows.map((r) => [r.severity, r.to])).toEqual([
      ["fail", "/admin/telegram"],
      ["warn", "/admin/integrations?card=erp&panel=open"],
    ]);
  });
});

describe("зоны без ответственного", () => {
  it("строка только если такие зоны есть; ведёт на «Зоны ответственности»", () => {
    expect(zoneRows(0)).toEqual([]);
    expect(zoneRows(2)).toMatchObject([
      { kind: "zones", to: "/admin/zones", page: "zones", params: { count: 2 } },
    ]);
  });
});

describe("обращения и обмен", () => {
  it("обращения — только если они есть", () => {
    expect(ticketRows(0)).toEqual([]);
    expect(ticketRows(3)).toMatchObject([{ kind: "tickets", to: "/dashboard/queue" }]);
  });

  it("очередь обмена: ждёт и не доставлено — суммы по доменам", () => {
    expect(
      busLine([
        { outbox_pending: 2, dlq_size: 0 },
        { outbox_pending: 1, dlq_size: 4 },
      ]),
    ).toEqual({ queued: 3, dead: 4 });
  });
});

describe("готовность: «заполнено» и «работает» — разные факты", () => {
  it.each([
    ["done", "ok", "works"],
    ["done", "fail", "broken"],
    ["done", "warn", "broken"],
    ["done", undefined, "filled"],
    ["done", "unknown", "filled"],
    ["todo", "ok", "todo"],
    ["unknown", undefined, "unknown"],
  ] as const)("шаг %s, проверка службы %s → %s", (step, card, expected) => {
    expect(readinessState(step, card)).toBe(expected);
  });
});
