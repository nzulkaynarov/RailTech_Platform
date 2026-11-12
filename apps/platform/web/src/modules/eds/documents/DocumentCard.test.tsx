import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  type MockDocument,
  documentId,
  readEds,
  writeEds,
} from "../../../mocks/fixtures/edsDocuments";
import { panelEl, renderAt, setupEdsTests, signIn } from "../../../test/edsKit";

setupEdsTests();

vi.mock("../../../shared/ui/PdfViewer", () => ({
  default: ({ name }: { name: string }) => <div data-testid="pdf-pages">{name}</div>,
}));

const ID = documentId(901);
const AT = "2026-11-01T09:00:00Z";

const cell = (text: string, header = false) => ({
  type: header ? "tableHeader" : "tableCell",
  content: [{ type: "paragraph", content: [{ type: "text", text }] }],
});

function seed(overrides: Partial<MockDocument>): void {
  const state = readEds();
  state.documents.push({
    id: ID,
    kind: "letter_out",
    number: null,
    status: "draft",
    version: 1,
    subject: "Сверка поставок за октябрь",
    text: "Просим сверить поставки.\n\nПозиция | Кол-во\nРельс Р65 | 12",
    ownerId: "u-demo-universal",
    amount: null,
    due_date: null,
    file_ids: [],
    erp_deal_id: null,
    recipient: { name: "ООО «Вымышленный завод»", inn: null },
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
            { type: "paragraph", content: [{ type: "text", text: "Просим сверить поставки." }] },
            {
              type: "bulletList",
              content: [
                {
                  type: "listItem",
                  content: [{ type: "paragraph", content: [{ type: "text", text: "акт сверки" }] }],
                },
              ],
            },
            {
              type: "table",
              attrs: { variant: "grid" },
              content: [
                { type: "tableRow", content: [cell("Позиция", true), cell("Кол-во", true)] },
                { type: "tableRow", content: [cell("Рельс Р65"), cell("12")] },
              ],
            },
          ],
        },
      },
      recipient_attention: null,
      recipient_email: null,
      signatory_name: null,
      signatory_position: null,
      pdf: null,
      pdfPolls: 0,
      mailings: [],
      registration_requested: null,
    },
    ...overrides,
  });
  writeEds(state);
}

async function openCard() {
  signIn("manager@demo.example");
  renderAt(`/eds/documents?scope=all&doc=${ID}&panel=open`);
  const panel = await panelEl();
  expect(
    await within(panel).findByRole("heading", { level: 3, name: "Сверка поставок за октябрь" }),
  ).toBeVisible();
  return within(panel);
}

describe("EDS · карточка письма: текст блоками, без неприменимых полей", () => {
  it.each([
    ["черновик", { status: "draft", number: null }],
    ["зарегистрированное", { status: "sent", number: "ИСХ-045/26" }],
  ] as const)(
    "%s: таблица тела — таблицей с шапкой, а не строками «a | b»",
    async (_name, state) => {
      seed(state);
      const card = await openCard();

      expect(card.getByText("Просим сверить поставки.")).toBeVisible();
      expect(card.getByText("акт сверки").closest("ul")).not.toBeNull();
      const table = card.getByRole("table", { name: "Таблица в тексте письма" });
      expect(within(table).getByRole("columnheader", { name: "Позиция" })).toBeVisible();
      expect(within(table).getByRole("columnheader", { name: "Кол-во" })).toBeVisible();
      expect(within(table).getByRole("cell", { name: "Рельс Р65" })).toBeVisible();
      expect(card.queryByText(/Позиция \| Кол-во/)).toBeNull();
    },
  );

  it("у письма нет «Суммы» и пустых полей; адресат и тип — есть", async () => {
    seed({});
    const card = await openCard();

    expect(card.queryByText("Сумма")).toBeNull();
    expect(card.queryByText("Нужно до")).toBeNull();
    expect(card.queryByText("Проект")).toBeNull();
    expect(card.getByText("Адресат")).toBeVisible();
    expect(card.getByText("ООО «Вымышленный завод»")).toBeVisible();
    expect(card.getByText("Тип")).toBeVisible();
    // маршрута согласования у письма нет — пустых блоков «Маршрут» и «Решения» тоже
    expect(card.queryByRole("heading", { level: 4, name: "Маршрут" })).toBeNull();
    expect(card.queryByRole("heading", { level: 4, name: "Решения" })).toBeNull();
  });

  it("письмо без бланка (только текст): плоский текст, как раньше", async () => {
    seed({ text: "Короткое письмо без бланка." });
    const state = readEds();
    const doc = state.documents.find((d) => d.id === ID);
    if (doc?.letter) doc.letter.body = null;
    writeEds(state);
    const card = await openCard();

    expect(card.getByText("Короткое письмо без бланка.")).toBeVisible();
    expect(card.queryByRole("table")).toBeNull();
  });

  it("у служебной записки с суммой поле «Сумма» остаётся", async () => {
    seed({ kind: "memo", amount: { amount: "1500000.00", currency: "UZS" }, letter: undefined });
    const card = await openCard();

    expect(card.getByText("Сумма")).toBeVisible();
    expect(card.getByText("1 500 000 сум")).toBeVisible();
  });

  it("ответ на входящее: «В ответ на ВХ-…» со ссылкой; не ушло адресату — метка «Не отправлено» и «Отправить адресату ещё раз» (EDS-REPLY-1)", async () => {
    seed({ status: "sent", number: "ИСХ-045/26", replyTo: "ВХ-108/26" });
    const state = readEds();
    const doc = state.documents.find((d) => d.id === ID);
    if (doc?.letter) {
      doc.letter.recipient_email = "office@nosmtp.example";
      doc.letter.mailings = [
        {
          id: "m-1",
          to: ["office@nosmtp.example"],
          status: "failed",
          reason: "Почта не настроена — Настройки · Подключения · Почта",
          requested_by: null,
          requested_at: "2026-11-01T09:05:00Z",
          finished_at: "2026-11-01T09:06:00Z",
        },
      ];
    }
    writeEds(state);
    signIn("registrar@demo.example");
    renderAt(`/eds/documents?scope=all&doc=${ID}&panel=open`);
    const panel = within(await panelEl());

    const link = await panel.findByRole("link", { name: /ВХ-108\/26/ });
    expect(link).toHaveAttribute("href", `/eds/inbox/${encodeURIComponent("ВХ-108/26")}`);
    expect(panel.getByText("В ответ на")).toBeVisible();
    expect(panel.getByText("Не отправлено")).toBeVisible();
    expect(panel.getByRole("button", { name: "Отправить адресату ещё раз" })).toBeVisible();
  });
});
