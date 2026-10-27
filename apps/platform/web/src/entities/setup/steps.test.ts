import { describe, expect, it } from "vitest";

import type { SetupChecklist, SetupStepState } from "../../shared/api/generated/model";
import { STEP_TARGET, needsSetup, nextStep } from "./steps";

function checklist(
  states: SetupStepState[],
  company: SetupChecklist["company"] = { required: false, can_setup: false },
): SetupChecklist {
  const keys = ["bot", "erp", "mail", "models", "first_employee"] as const;
  const steps = keys.map((key, index) => ({ key, state: states[index] ?? "done" }));
  return {
    steps,
    done: steps.filter((s) => s.state === "done").length,
    total: 5,
    company,
  };
}

describe("шаги чек-листа", () => {
  it("каждый шаг ведёт на свой экран", () => {
    expect(STEP_TARGET.bot).toContain("/admin/integrations?card=telegram");
    expect(STEP_TARGET.erp).toContain("card=erp");
    expect(STEP_TARGET.mail).toContain("card=mail");
    expect(STEP_TARGET.models).toContain("card=models");
    expect(STEP_TARGET.first_employee).toBe("/admin/org?invite=open&panel=open");
  });

  it("следующий шаг — первый несделанный", () => {
    expect(nextStep(checklist(["done", "todo", "todo", "done", "done"]))?.key).toBe("erp");
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
