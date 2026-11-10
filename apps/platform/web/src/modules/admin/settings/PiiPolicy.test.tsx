import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetFeedMocks } from "../../../mocks/feedHandlers";
import { readKb } from "../../../mocks/fixtures/kb";
import { readDocflowSettings, resetLetterIntakeMock } from "../../../mocks/letterIntake";
import { endSession } from "../../../mocks/mockSession";
import { resetTicketsMock } from "../../../mocks/ticketsStore";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
  resetFeedMocks();
  resetTicketsMock();
  resetLetterIntakeMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const page = () => screen.findByRole("heading", { level: 1, name: "Расходы на ИИ" });
const policy = () => screen.findByRole("region", { name: "Защита данных для ИИ" });

describe("Настройки · Расходы на ИИ · Защита данных для ИИ (PD-BIZ)", () => {
  it("по умолчанию «Деловая»: у каждой политики одно предложение о том, что скрывается; сканы читаются с подписью", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/ai-spend");
    await page();
    const card = within(await policy());
    const business = card.getByRole("radio", { name: /Деловая \(рекомендуется\)/ });
    expect(business).toBeChecked();
    expect(business).toHaveAccessibleName(/паспорт, ПИНФЛ, номера карт и даты рождения/);
    expect(card.getByRole("radio", { name: /Строгая/ })).not.toBeChecked();
    expect(card.getByText(/Скрываются ещё телефоны, почта, ИНН и счета/)).toBeVisible();
    expect(card.getByRole("button", { name: "Сохранить" })).toBeDisabled();

    const scans = await screen.findByRole("switch", { name: "Читать сканы и фото писем" });
    expect(scans).toBeChecked();
    expect(scans).toBeEnabled();
    expect(screen.getByText("Паспорта и личные документы не загружайте.")).toBeVisible();
  });

  it("админ выбирает «Строгую» и сохраняет: CRM получает политику, сканы выключаются и блокируются", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/ai-spend");
    await page();
    const card = within(await policy());
    fireEvent.click(card.getByRole("radio", { name: /Строгая/ }));
    expect(await screen.findByText("Есть несохранённые изменения")).toBeVisible();
    // до сохранения CRM ничего не получила
    expect(readKb().settings["ai"]).toEqual({ pii_policy: "business" });
    fireEvent.click(card.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(readKb().settings["ai"]).toEqual({ pii_policy: "strict" });
    });
    expect(await screen.findByText("Политика сохранена: «Строгая»")).toBeVisible();
    // EDS узнаёт политику из CRM (в моках — сразу): сканы не читаются, переключатель заблокирован с пояснением
    expect(readDocflowSettings().pii_policy).toBe("strict");
    const scans = await screen.findByRole("switch", { name: "Читать сканы и фото писем" });
    await waitFor(() => {
      expect(scans).toBeDisabled();
    });
    expect(scans).not.toBeChecked();
    expect(
      screen.getByText("При «Строгой» политике сканы и фото в модель не отправляются."),
    ).toBeVisible();
  });

  it("админ выключает сканы при «Деловой»: настройка EDS сохраняется", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/ai-spend");
    await page();
    fireEvent.click(await screen.findByRole("switch", { name: "Читать сканы и фото писем" }));
    await waitFor(() => {
      expect(readDocflowSettings().recognize_scans).toBe(false);
    });
    expect(await screen.findByText("Настройка сохранена")).toBeVisible();
    expect(screen.getByRole("switch", { name: "Читать сканы и фото писем" })).not.toBeChecked();
  });

  it("директор только смотрит: политика и переключатель заблокированы, кнопки «Сохранить» нет", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/ai-spend");
    await page();
    const card = within(await policy());
    expect(card.getByRole("radio", { name: /Деловая/ })).toBeDisabled();
    expect(card.queryByRole("button", { name: "Сохранить" })).toBeNull();
    expect(await screen.findByRole("switch", { name: "Читать сканы и фото писем" })).toBeDisabled();
  });

  it("документооборот отстаёт от CRM: предупреждение и фактическое состояние сканов", async () => {
    // CRM — «Деловая», а проекция в EDS ещё «Строгая» (событие не дошло): переключатель показывает EDS, не CRM.
    server.use(
      http.get("*/eds/docflow-settings", () =>
        HttpResponse.json({ recognize_scans: true, pii_policy: "strict", ai_available: true }),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/ai-spend");
    await page();
    expect(
      await screen.findByText(
        /Документооборот ещё не применил политику «Деловая \(рекомендуется\)»/,
      ),
    ).toBeVisible();
    expect(screen.getByText(/пока работает по «Строгая»/)).toBeVisible();
    const scans = await screen.findByRole("switch", { name: "Читать сканы и фото писем" });
    expect(scans).toBeDisabled();
    expect(scans).not.toBeChecked();
  });

  it("политики совпадают — предупреждения нет", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/ai-spend");
    await page();
    await policy();
    await screen.findByRole("switch", { name: "Читать сканы и фото писем" });
    expect(screen.queryByText(/Документооборот ещё не применил политику/)).toBeNull();
  });
});
