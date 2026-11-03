import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";

import { readDictionaries, writeDictionaries } from "../../../mocks/dictionaries";
import { readResolutionTemplates } from "../../../mocks/resolutionTemplates";
import type { OfficeResolutionIn } from "../../../shared/api/generated/model";
import { chooseOption } from "../../../test/fields";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";
import { server } from "../../../test/server";
import { applyTemplate, daysUntil, dueIn, templateFromForm } from "./officeModel";

setupLetterTests();

const TAX = "/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution";

async function directorForm() {
  signIn("director@demo.example");
  renderAt(TAX);
  return screen.findByRole("form", { name: "Резолюция директора" }, { timeout: 10_000 });
}

describe("Шаблоны резолюций в форме (EDS-REG, R2)", () => {
  it("«Из шаблона» заполняет форму, директор правит и накладывает", async () => {
    let body = null as OfficeResolutionIn | null;
    server.use(
      http.post("*/eds/letters/:id/office-resolution", async ({ request }) => {
        body = (await request.clone().json()) as OfficeResolutionIn;
        return undefined;
      }),
    );
    const form = await directorForm();
    await chooseOption(within(form).getByLabelText("Из шаблона"), "Налоговая — ответ бухгалтерии");
    expect(within(form).getByRole("radio", { name: /Подготовить ответ/ })).toBeChecked();
    expect(within(form).getByLabelText("Текст резолюции")).toHaveValue(
      "Подготовить ответ в срок, проект — мне на согласование.",
    );
    fireEvent.change(within(form).getByLabelText("Текст резолюции"), {
      target: { value: "Подготовить ответ до пятницы." },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Наложить резолюцию" }));
    await waitFor(() => {
      expect(body).not.toBeNull();
    });
    expect(body).toMatchObject({
      kind: "reply",
      responsible_id: "u-demo-accountant",
      text: "Подготовить ответ до пятницы.",
    });
  });

  it("«Сохранить как шаблон» — личный шаблон директора", async () => {
    const form = await directorForm();
    await chooseOption(within(form).getByLabelText("Ответственный"), "Демо Широков");
    fireEvent.click(within(form).getByRole("button", { name: "Сохранить как шаблон" }));
    const dialog = await screen.findByRole("dialog", { name: "Сохранить как шаблон" });
    expect(within(dialog).queryByRole("checkbox")).toBeNull(); // общий — только администратору
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await within(dialog).findByText("Укажите название.")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Название шаблона"), {
      target: { value: "Исполнить — Широков" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Шаблон «Исполнить — Широков» сохранён.")).toBeInTheDocument();
    const saved = readResolutionTemplates().find((t) => t.name === "Исполнить — Широков");
    expect(saved).toMatchObject({ scope: "personal", kind: "execute", ownerId: "u-demo-director" });
    expect(saved?.responsible?.id).toBe("u-demo-universal");
  });

  it("названия видов резолюции — из справочника", async () => {
    const state = readDictionaries();
    writeDictionaries({
      ...state,
      "resolution-kinds": state["resolution-kinds"].map((item) =>
        item.code === "info" ? { ...item, name: { ru: "Ознакомиться", uz: "", en: "" } } : item,
      ),
    });
    const form = await directorForm();
    expect(await within(form).findByRole("radio", { name: /Ознакомиться/ })).toBeInTheDocument();
  });
});

describe("officeModel: шаблоны", () => {
  const letter = {
    addressee: { id: "u-demo-director", name: "Демо Директоров", initials: "ДД" },
    suggested_due: "2026-11-12",
  };
  const base = {
    id: "t1",
    name: "Т",
    scope: "company" as const,
    text: "Исполнить",
    co_executors: [],
    acquaint: [],
    owner: null,
    editable: true,
  };

  it("ответственный «адресат» — адресат письма; срок — через N рабочих дней, иначе подсказка", () => {
    const values = applyTemplate(
      { ...base, kind: "execute", responsible_type: "addressee", responsible: null, due_days: 5 },
      letter,
      "2026-11-02",
    );
    expect(values.responsibleId).toBe("u-demo-director");
    expect(values.due).toBe("2026-11-09"); // пн + 5 = сб → пн
    const noDays = applyTemplate(
      { ...base, kind: "execute", responsible_type: "none", responsible: null, due_days: null },
      letter,
      "2026-11-02",
    );
    expect([noDays.responsibleId, noDays.due]).toEqual(["", "2026-11-12"]);
    const info = applyTemplate(
      { ...base, kind: "info", responsible_type: "addressee", responsible: null, due_days: 5 },
      letter,
      "2026-11-02",
    );
    expect([info.responsibleId, info.due]).toEqual(["", ""]);
  });

  it("форма → шаблон: срок в днях, без ответственного — «выбрать при резолюции»", () => {
    expect(dueIn("2026-11-06", 1)).toBe("2026-11-09"); // пт + 1 = сб → пн
    expect(daysUntil("2026-11-02", "2026-11-12")).toBe(10);
    const body = templateFromForm(
      {
        kind: "reply",
        responsibleId: "",
        due: "2026-11-05",
        text: " Ответить ",
        templated: false,
        coIds: [],
        acquaintIds: ["7", "7"],
      },
      " Ответ ",
      "personal",
      "2026-11-02",
    );
    expect(body).toEqual({
      name: "Ответ",
      scope: "personal",
      kind: "reply",
      text: "Ответить",
      responsible_type: "none",
      responsible_id: null,
      co_executor_ids: [],
      acquaint_ids: ["7"],
      due_days: 3,
    });
  });
});
