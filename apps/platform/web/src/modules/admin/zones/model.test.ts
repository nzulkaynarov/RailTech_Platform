import { describe, expect, it } from "vitest";

import { langOf, sectionLabel, slugOf, zoneText } from "./model";

describe("модель зон", () => {
  it("название и описание — на языке интерфейса, неизвестный язык — русский", () => {
    const text = { ru: "Финансы", uz: "Moliya", en: "Finance" };
    expect(zoneText(text, "uz")).toBe("Moliya");
    expect(zoneText(text, "en-GB")).toBe("Finance");
    expect(zoneText(text, "de")).toBe("Финансы");
    expect(langOf("uz-Latn")).toBe("uz");
  });

  it("слаг — латиница из английского названия; без пригодного названия — запасной", () => {
    expect(slugOf("Quality & Control")).toBe("quality_control");
    expect(slugOf("Качество")).toMatch(/^zone_[a-z0-9]+$/);
  });

  it("подпись раздела — из каталога, неизвестный ключ — как есть", () => {
    expect(sectionLabel("eds.payments", "en")).toBe(
      "Operations · Finance · confirm payment, request a payment order",
    );
    expect(sectionLabel("no.such", "ru")).toBe("no.such");
  });
});
