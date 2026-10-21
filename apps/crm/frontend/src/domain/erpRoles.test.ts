import { describe, expect, it } from "vitest";

import { UserOutErpRoleCodesItem } from "../api/generated/model";
import {
  ERP_ROLE_CODES,
  ERP_ROLE_LABELS,
  erpRoleHint,
  erpRoleLabel,
  erpRoleOptions,
  erpRolesOf,
  isErpSuperuser,
} from "./erpRoles";

describe("роли ERP из CRM (FIX-63)", () => {
  it("перечень совпадает с контрактом (сгенерированный enum) и порядком каталога ERP", () => {
    expect([...ERP_ROLE_CODES]).toEqual(Object.values(UserOutErpRoleCodesItem));
    expect(ERP_ROLE_CODES[0]).toBe("CALCULATION");
    expect(ERP_ROLE_CODES.at(-1)).toBe("VIEWER");
  });

  it.each(ERP_ROLE_CODES)("у роли %s есть название и описание на ru, uz и en", (code) => {
    for (const language of ["ru", "uz", "en"] as const) {
      expect(ERP_ROLE_LABELS[code].name[language].trim()).not.toBe("");
      expect(ERP_ROLE_LABELS[code].hint[language].trim()).not.toBe("");
    }
  });

  it("русские названия — как в ERP («Настройки → Команда»)", () => {
    expect(ERP_ROLE_CODES.map((code) => erpRoleLabel(code))).toEqual([
      "Расчёт",
      "Каталог и закупки",
      "Исполнение и логистика",
      "Финансы",
      "Руководитель",
      "Наблюдатель",
    ]);
  });

  it("язык выбирается аргументом, неизвестный код показывается как есть", () => {
    expect(erpRoleLabel("FINANCE", "en")).toBe("Finance");
    expect(erpRoleLabel("FINANCE", "uz")).toBe("Moliya");
    expect(erpRoleHint("HEAD")).toContain("утвержд");
    expect(erpRoleLabel("ROOT")).toBe("ROOT");
    expect(erpRoleHint("ROOT")).toBe("");
  });

  it("варианты выбора: значение — код, подпись — название и описание", () => {
    const options = erpRoleOptions();
    expect(options.map((o) => o.value)).toEqual([...ERP_ROLE_CODES]);
    expect(options[3]).toMatchObject({ value: "FINANCE", title: "Финансы" });
  });

  it("erpRolesOf читает поле пользователя терпимо", () => {
    expect(erpRolesOf({ erp_role_codes: ["HEAD", "FINANCE"] })).toEqual(["HEAD", "FINANCE"]);
    expect(erpRolesOf({})).toEqual([]);
    expect(erpRolesOf(null)).toEqual([]);
    expect(erpRolesOf({ erp_role_codes: undefined })).toEqual([]);
  });

  it("администратор CRM — суперпользователь ERP", () => {
    expect(isErpSuperuser({ roles: ["admin"] })).toBe(true);
    expect(isErpSuperuser({ roles: ["manager", "viewer"] })).toBe(false);
  });
});
