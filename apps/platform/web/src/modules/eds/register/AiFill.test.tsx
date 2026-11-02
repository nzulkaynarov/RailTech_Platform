import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { resetEds } from "../../../mocks/fixtures/edsDocuments";
import { intakeDecisions, writeDocflowSettings } from "../../../mocks/letterIntake";
import type { LetterRegisterIn } from "../../../shared/api/generated/model";
import { selectedLabel } from "../../../test/fields";
import { renderAt, signIn } from "../../../test/edsKit";
import { setupLetterTests } from "../../../test/lettersKit";
import { server } from "../../../test/server";
import { applySuggestion, decisionOf, revertSuggestion } from "./aiFill";
import { emptyRegister } from "./registerModel";

setupLetterTests();

async function openForm() {
  resetEds();
  signIn("registrar@demo.example");
  renderAt("/eds/register");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Зарегистрировать входящее" }),
  ).toBeVisible();
}

async function attach(name = "trebovanie.pdf", type = "application/pdf") {
  fireEvent.change(screen.getByLabelText("Файл документа"), {
    target: { files: [new File(["%PDF-1.4"], name, { type })] },
  });
  const list = await screen.findByRole("list", { name: "Прикреплённые файлы" });
  expect(await within(list).findByText("загружен")).toBeVisible();
}

describe("«Заполнить из файла» (EDS-REG)", () => {
  it("предлагает поля, помечает их, правка снимает пометку; регистрация — решение «поправил»", async () => {
    let body = null as LetterRegisterIn | null;
    const searched: string[] = [];
    server.use(
      http.post("*/eds/letters", async ({ request }) => {
        body = (await request.clone().json()) as LetterRegisterIn;
        return undefined;
      }),
      // Связь с проектом ищет код: сначала по ИНН (пусто), затем по названию корреспондента.
      http.get("*/eds/deal-options", ({ request }) => {
        const q = new URL(request.url).searchParams.get("q") ?? "";
        searched.push(q);
        const items =
          q === "ГНИ Демо-района"
            ? [
                {
                  erp_deal_id: 905,
                  number: "ЗВ-2026-905",
                  title: "Сверка НДС",
                  company: "ГНИ Демо-района",
                },
              ]
            : [];
        return HttpResponse.json({ items, sources: { crm: "ok", erp: "ok" } });
      }),
    );
    await openForm();
    expect(await screen.findByText("Сначала приложите файл письма.")).toBeVisible();
    await attach();
    fireEvent.click(screen.getByRole("button", { name: "Заполнить из файла" }));

    expect(await screen.findByText(/Заполнено из файла: 8 полей/)).toBeVisible();
    expect(screen.getByLabelText("Корреспондент")).toHaveValue("ГНИ Демо-района");
    expect(screen.getByLabelText("ИНН корреспондента")).toHaveValue("301234567");
    expect(screen.getByLabelText("Тема")).toHaveValue(
      "Требование о пояснениях по НДС за III квартал",
    );
    expect(selectedLabel(screen.getByLabelText("Вид документа"))).toBe(
      "Требование или уведомление ГНК",
    );
    expect(screen.getByRole("checkbox", { name: "Срочно" })).toBeChecked();
    expect(screen.getAllByText("Предложено ИИ")).toHaveLength(8);

    fireEvent.change(screen.getByLabelText("Тема"), { target: { value: "Пояснения по НДС" } });
    expect(screen.getAllByText("Предложено ИИ")).toHaveLength(7);
    expect(await screen.findByText(/Возможная связь: ЗВ-2026-905/)).toBeVisible();
    expect(searched).toContain("301234567");
    expect(searched).toContain("ГНИ Демо-района");

    // способ получения помощник не предлагает — его выбирает человек
    fireEvent.mouseDown(screen.getByLabelText("Способ получения"));
    fireEvent.click(await screen.findByTitle("Почта"));
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));
    expect(await screen.findByText(/Зарегистрировано: ВХ-/)).toBeVisible();
    await waitFor(() => {
      expect(intakeDecisions).toEqual(["edited"]);
    });
    expect(body).toMatchObject({
      subject: "Пояснения по НДС",
      sender_ref_number: "04-12/7788",
      kind: "tax_notice",
    });
  });

  it("скан при выключенном распознавании — понятный отказ, форма остаётся ручной", async () => {
    await openForm();
    await attach("скан.png", "image/png");
    fireEvent.click(await screen.findByRole("button", { name: "Заполнить из файла" }));
    expect(await screen.findByText(/распознавание сканов выключено/)).toBeVisible();
    expect(screen.getByLabelText("Корреспондент")).toHaveValue("");
  });

  it("«Убрать предложенное» очищает непоправленные поля и пишет «вручную»", async () => {
    writeDocflowSettings({ recognize_scans: true, ai_available: true });
    await openForm();
    fireEvent.change(screen.getByLabelText("Тема"), { target: { value: "Своя тема" } });
    await attach();
    fireEvent.click(screen.getByRole("button", { name: "Заполнить из файла" }));
    expect(await screen.findByText(/Заполнено из файла: 7 полей/)).toBeVisible();
    expect(screen.getByLabelText("Тема")).toHaveValue("Своя тема"); // набранное человеком не перетирается
    fireEvent.click(screen.getByRole("button", { name: "Убрать предложенное" }));
    expect(screen.getByLabelText("Корреспондент")).toHaveValue("");
    expect(screen.getByLabelText("Тема")).toHaveValue("Своя тема");
    await waitFor(() => {
      expect(intakeDecisions).toEqual(["manual"]);
    });
  });

  it("помощник не настроен — кнопки нет", async () => {
    writeDocflowSettings({ recognize_scans: false, ai_available: false });
    await openForm();
    await attach();
    expect(screen.queryByRole("button", { name: "Заполнить из файла" })).toBeNull();
  });
});

describe("aiFill", () => {
  it("вид — только из справочника; решение — принял или поправил", () => {
    const fields = {
      sender_name: "Банк",
      sender_inn: null,
      sender_ref_number: null,
      sender_ref_date: null,
      subject: "Тарифы",
      summary: null,
      kind: "lottery",
      document_due: null,
    };
    const result = applySuggestion(emptyRegister("2026-11-01"), fields, [
      { code: "bank", name: { ru: "Банк", uz: "", en: "" }, urgent: false },
    ]);
    expect(result.filled).toEqual(["senderName", "subject"]);
    expect(result.values.kind).toBe("");
    expect(decisionOf(result.filled, new Set(result.filled))).toBe("accepted");
    expect(decisionOf(result.filled, new Set(["senderName"]))).toBe("edited");
    expect(revertSuggestion(result.values, ["subject"]).subject).toBe("");
  });
});
