import { describe, expect, it } from "vitest";

import type { SetupChecklist, SetupStepState } from "../../shared/api/generated/model";
import { STEP_TARGET, needsSetup, nextStep, staysOnCompany, stepAfter } from "./steps";

function checklist(
  states: SetupStepState[],
  company: SetupChecklist["company"] = { required: false, can_setup: false },
): SetupChecklist {
  const keys = ["erp", "bot", "mail", "models", "first_employee"] as const;
  const steps = keys.map((key, index) => ({ key, state: states[index] ?? "done" }));
  return {
    steps,
    done: steps.filter((s) => s.state === "done").length,
    total: 5,
    company,
    company_blocker: null,
  };
}

describe("после ERP мастер остаётся на компании (W15-G-10)", () => {
  it("компании нет — форма; ERP не выдала доступ — ждём; компания готова или ERP не сопряжена — дальше", () => {
    expect(staysOnCompany(checklist(["done"], { required: true, can_setup: true }))).toBe(true);
    expect(
      staysOnCompany({ ...checklist(["done"], null), company_blocker: "erp_unavailable" }),
    ).toBe(true);
    expect(staysOnCompany(checklist(["done"], { required: false, can_setup: false }))).toBe(false);
    expect(
      staysOnCompany({ ...checklist(["todo"], null), company_blocker: "erp_not_connected" }),
    ).toBe(false);
  });
});

describe("шаги чек-листа", () => {
  it("каждый шаг открывается внутри мастера, в его боковом окне (W15-H4)", () => {
    expect(STEP_TARGET.bot).toBe("/admin/setup?step=bot&panel=open");
    expect(STEP_TARGET.erp).toBe("/admin/setup?step=erp&panel=open");
    expect(STEP_TARGET.mail).toBe("/admin/setup?step=mail&panel=open");
    expect(STEP_TARGET.models).toBe("/admin/setup?step=models&panel=open");
    expect(STEP_TARGET.first_employee).toBe("/admin/setup?step=first_employee&panel=open");
  });

  it("после шага — следующий несделанный, раньше стоящие несделанные тоже не теряются", () => {
    // порядок в чек-листе: erp, bot, mail, models, first_employee
    expect(stepAfter(checklist(["done", "todo", "todo", "done", "done"]), "bot")?.key).toBe("mail");
    expect(stepAfter(checklist(["done", "done", "done", "done", "todo"]), "mail")?.key).toBe(
      "first_employee",
    );
    expect(stepAfter(checklist(["todo", "done", "done", "done", "done"]), "models")?.key).toBe(
      "erp",
    );
    expect(stepAfter(checklist(["done", "done", "done", "done", "done"]), "bot")).toBeUndefined();
  });

  it("следующий шаг — первый несделанный", () => {
    expect(nextStep(checklist(["todo", "todo", "todo", "done", "done"]))?.key).toBe("erp");
    expect(nextStep(checklist(["done", "todo", "todo", "done", "done"]))?.key).toBe("bot");
    expect(nextStep(checklist(["done", "unknown", "done", "done", "done"]))).toBeUndefined();
  });

  it("баннер нужен, пока есть несделанное или нет своей компании", () => {
    expect(needsSetup(checklist(["done", "done", "todo", "done", "done"]))).toBe(true);
    expect(needsSetup(checklist([], { required: true, can_setup: true }))).toBe(true);
    expect(needsSetup(checklist([]))).toBe(false);
    expect(needsSetup(checklist([], null))).toBe(false);
  });

  it("«нет данных» баннер не включает", () => {
    expect(needsSetup(checklist(["unknown", "unknown", "unknown", "unknown", "unknown"]))).toBe(
      false,
    );
  });
});
