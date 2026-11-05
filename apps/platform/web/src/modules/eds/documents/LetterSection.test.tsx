import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  type MockDocument,
  documentId,
  readEds,
  writeEds,
} from "../../../mocks/fixtures/edsDocuments";
import { findModal } from "../../../test/catalogKit";
import { panelEl, renderAt, setupEdsTests, signIn } from "../../../test/edsKit";

setupEdsTests();

vi.mock("../../../shared/ui/PdfViewer", () => ({
  default: ({ name }: { name: string }) => <div data-testid="pdf-pages">{name}</div>,
}));

const ID = documentId(900);
const AT = "2026-11-01T09:00:00Z";

function seed(overrides: Partial<MockDocument>): void {
  const state = readEds();
  state.documents.push({
    id: ID,
    kind: "letter_out",
    number: null,
    status: "draft",
    version: 1,
    subject: "Ответ на требование ГНК",
    text: "Направляем пояснения.",
    ownerId: "u-demo-universal",
    amount: null,
    due_date: null,
    file_ids: [],
    erp_deal_id: null,
    recipient: { name: "ГНИ Мирабадского района", inn: null },
    decisions: [],
    created_at: AT,
    updated_at: AT,
    replyTo: null,
    letter: {
      body: {
        version: 1,
        lang: "ru",
        doc: {
          type: "doc",
          content: [
            { type: "paragraph", content: [{ type: "text", text: "Направляем пояснения." }] },
          ],
        },
      },
      recipient_attention: "Начальнику ГНИ",
      recipient_email: "gni@example.uz",
      signatory_name: null,
      signatory_position: null,
      pdf: null,
      pdfPolls: 0,
      mailings: [],
      registration_requested: { ownerId: "u-demo-universal", at: AT },
    },
    ...overrides,
  });
  writeEds(state);
}

async function openCard(email: string) {
  signIn(email);
  renderAt(`/eds/documents?scope=all&doc=${ID}&panel=open`);
  const panel = await panelEl();
  expect(
    await within(panel).findByRole("heading", { level: 3, name: "Ответ на требование ГНК" }),
  ).toBeVisible();
  return within(panel);
}

describe("EDS · карточка письма на бланке (P4)", () => {
  it("делопроизводитель видит переданный черновик, регистрирует и отправляет: номер ИСХ и журнал отправки", async () => {
    seed({});
    const card = await openCard("registrar@demo.example");

    expect(card.getByText(/Передано на регистрацию: Демо Широков/)).toBeVisible();
    expect(card.getByText("Начальнику ГНИ")).toBeVisible();
    expect(card.getByText("по бланку (директор)")).toBeVisible();
    expect(card.getByText("Адресату ещё не отправляли.")).toBeVisible();
    fireEvent.click(card.getByRole("button", { name: "Зарегистрировать и отправить" }));

    expect(await screen.findByText(/Письмо зарегистрировано: ИСХ-\d{3}\/26/)).toBeVisible();
    const saved = readEds().documents.find((d) => d.id === ID);
    expect(saved?.status).toBe("sent");
    expect(saved?.letter?.pdf?.final).toBe(true);
    expect(saved?.letter?.mailings[0]?.to).toEqual(["gni@example.uz"]);
    // Адрес — и в реквизитах письма, и в строке журнала отправки (она может появиться позже): хватает любого видимого.
    const shown = await card.findAllByText(/gni@example\.uz/);
    expect(shown.length).toBeGreaterThan(0);
    expect(shown[0]).toBeVisible();
  });

  it("отправка не удалась — причина словами; «Отправить адресату ещё раз» добавляет строку журнала", async () => {
    seed({
      number: "ИСХ-090/26",
      status: "sent",
      ownerId: "u-demo-registrar",
    });
    const state = readEds();
    const doc = state.documents.find((d) => d.id === ID);
    if (doc?.letter) {
      doc.letter.registration_requested = null;
      doc.letter.pdf = {
        status: "ready",
        final: true,
        error: null,
        pages: 1,
        requested_at: AT,
        ready_at: AT,
      };
      doc.letter.mailings = [
        {
          id: "m-1",
          to: ["gni@example.uz"],
          status: "failed",
          reason: "Почта не настроена — Настройки · Подключения · Почта",
          requested_by: null,
          requested_at: AT,
          finished_at: AT,
        },
      ];
    }
    writeEds(state);
    const card = await openCard("registrar@demo.example");

    expect(
      card.getByText("Не отправлено: Почта не настроена — Настройки · Подключения · Почта"),
    ).toBeVisible();
    expect(card.getByText("PDF с номером ИСХ готов · 1 стр.")).toBeVisible();
    fireEvent.click(card.getByRole("button", { name: "Отправить адресату ещё раз" }));
    expect(await screen.findByText("Отправка запрошена")).toBeVisible();
    await waitFor(() => {
      expect(readEds().documents.find((d) => d.id === ID)?.letter?.mailings).toHaveLength(2);
    });
  });

  it("автор без права регистрировать: «Передать на регистрацию», кнопки регистрации нет", async () => {
    seed({});
    const state = readEds();
    const doc = state.documents.find((d) => d.id === ID);
    if (doc?.letter) doc.letter.registration_requested = null;
    writeEds(state);
    const card = await openCard("universal@demo.example");

    expect(card.queryByRole("button", { name: "Зарегистрировать и отправить" })).toBeNull();
    fireEvent.click(card.getByRole("button", { name: "Передать на регистрацию" }));
    expect(await screen.findByText("Передано на регистрацию делопроизводителю.")).toBeVisible();
    expect(
      readEds().documents.find((d) => d.id === ID)?.letter?.registration_requested,
    ).not.toBeNull();
  });

  it("уполномоченное лицо видит кнопку «Подписать», выбирает способ отправки и подписывает письмо", async () => {
    seed({
      can_sign: true,
    });
    const state = readEds();
    const doc = state.documents.find((d) => d.id === ID);
    if (doc?.letter) doc.letter.registration_requested = null;
    writeEds(state);

    const card = await openCard("director@demo.example");
    const signBtn = card.getByRole("button", { name: "Подписать" });
    expect(signBtn).toBeVisible();

    fireEvent.click(signBtn);
    const modal = await findModal("Подписание исходящего письма");
    expect(within(modal).getByText("Способ отправки")).toBeDefined();

    const confirmBtn = within(modal).getByRole("button", { name: "Подписать письмо" });
    fireEvent.click(confirmBtn);

    expect(await screen.findByText(/Письмо подписано: ИСХ-\d{3}\/26/)).toBeVisible();
    const saved = readEds().documents.find((d) => d.id === ID);
    expect(saved?.status).toBe("sent");
    expect(saved?.signed_at).not.toBeNull();
    expect(saved?.verification_code).toMatch(/^RT-26-/);
  });
});
