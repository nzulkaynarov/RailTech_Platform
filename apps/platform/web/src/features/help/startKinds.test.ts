import { describe, expect, it } from "vitest";

import type { Me } from "../../shared/api/generated/model";
import { resources } from "../../shared/i18n";
import { START_KINDS, mergeSteps, startKindsOf } from "./startKinds";

const me = (resources: Record<string, "read" | "full">) => ({ resources }) as unknown as Me;

describe("startKindsOf", () => {
  it("по разделам каталога, а не по названию роли", () => {
    expect(startKindsOf(me({ "eds.payments": "full", "dashboard.queue": "full" }))).toEqual([
      "accountant",
    ]);
    expect(startKindsOf(me({ "eds.inbox": "full", "eds.memo.approve": "full" }))).toEqual([
      "director",
    ]);
    expect(startKindsOf(me({ "crm.leads": "full", "crm.clients": "full" }))).toEqual(["manager"]);
    expect(startKindsOf(me({ "erp.calc.goods": "full" }))).toEqual(["supply"]);
    expect(startKindsOf(me({ "erp.calc.services": "full" }))).toEqual(["engineer"]);
  });

  it("чтение не делает сотрудника исполнителем; администратор — первым", () => {
    expect(startKindsOf(me({ "eds.inbox": "read", admin: "read" }))).toEqual(["default"]);
    expect(startKindsOf(me({ "crm.leads": "full", admin: "full" }))).toEqual(["admin", "manager"]);
  });

  it("ничего подходящего — «любая роль»", () => {
    expect(startKindsOf(me({ "dashboard.queue": "full" }))).toEqual(["default"]);
  });
});

describe("startKindsOf: делопроизводитель, юрист и подписант (ЕВ-5а)", () => {
  it.each([
    ["регистрация входящих", { "eds.inbox": "read", "eds.inbox.register": "full" }, "registrar"],
    ["первая линия по лидам", { "crm.leads": "read", "crm.leads.triage": "full" }, "registrar"],
    ["виза юриста на договор", { "eds.visa.legal": "full" }, "lawyer"],
    ["реестр прав подписи", { "eds.signing.manage": "full" }, "signer"],
  ] as const)("%s → %s", (_name, resources, kind) => {
    expect(startKindsOf(me({ ...resources }))).toEqual([kind]);
  });

  it("чтение раздела вида не даёт", () => {
    expect(startKindsOf(me({ "eds.visa.legal": "read", "eds.signing.manage": "read" }))).toEqual([
      "default",
    ]);
  });

  it("несколько разделов — виды по каждому, в порядке списка", () => {
    expect(
      startKindsOf(
        me({
          "eds.inbox.register": "full",
          "eds.visa.legal": "full",
          "eds.signing.manage": "full",
        }),
      ),
    ).toEqual(["registrar", "lawyer", "signer"]);
  });

  it("решающий директор: регистрация и снабжение покрыты его текстом", () => {
    expect(
      startKindsOf(
        me({
          "eds.inbox": "full",
          "eds.inbox.register": "full",
          "eds.memo.approve": "full",
          "erp.calc.goods": "full",
          "erp.calc.services": "full",
        }),
      ),
    ).toEqual(["director"]);
  });

  it("у администратора права подписи покрыты его текстом", () => {
    expect(startKindsOf(me({ admin: "full", "eds.signing.manage": "full" }))).toEqual(["admin"]);
  });

  it("у каждого вида есть шаги и заголовок на трёх языках", () => {
    for (const lang of ["ru", "en", "uz"] as const) {
      const kinds = (
        resources[lang].help as unknown as {
          start: { kinds: Record<string, { title: string; steps: string[] }> };
        }
      ).start.kinds;
      for (const kind of [...START_KINDS, "default"]) {
        expect(kinds[kind]?.title, `${lang}.${kind}.title`).toBeTruthy();
        expect(kinds[kind]?.steps.length, `${lang}.${kind}.steps`).toBeGreaterThanOrEqual(3);
      }
    }
  });
});

describe("mergeSteps: приветствие первого входа", () => {
  const a = ["a1", "a2", "a3", "a4"];
  const b = ["b1", "b2", "b3"];
  it("один вид — его первые шаги", () => {
    expect(mergeSteps([a], 4)).toEqual(a);
  });
  it("несколько видов — по несколько шагов от каждого", () => {
    expect(mergeSteps([a, b], 4)).toEqual(["a1", "a2", "b1", "b2"]);
    expect(mergeSteps([a, b, ["c1"]], 4)).toEqual(["a1", "b1", "c1"]);
  });
});
