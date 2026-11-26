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

function seed(overrides: Partial<MockDocument>, handedOver = true): void {
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
    recipient: { name: "ГНИ Мирабадского района", inn: null, company_id: "7", contact_id: null },
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
      registration_requested: handedOver ? { ownerId: "u-demo-universal", at: AT } : null,
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
  it("делопроизводитель видит переданный черновик, но регистрации без подписи нет: ни «Зарегистрировать», ни «Подписать»", async () => {
    seed({ can_sign: false });
    const card = await openCard("registrar@demo.example");

    expect(card.getByText(/Передано на подпись: Демо Широков/)).toBeVisible();
    // СЦ-8: слово статуса — по факту передачи; статус документа остаётся `draft`
    expect(card.getByText("На подписи")).toBeVisible();
    expect(card.getByText("Начальнику ГНИ")).toBeVisible();
    expect(card.getByText("по бланку")).toBeVisible();
    expect(card.getByText("Адресату ещё не отправляли.")).toBeVisible();
    expect(card.queryByRole("button", { name: /Зарегистрировать/ })).toBeNull();
    expect(card.queryByRole("button", { name: "Подписать" })).toBeNull();
    expect(readEds().documents.find((d) => d.id === ID)?.status).toBe("draft");
  });

  it("до передачи на подпись письмо — «Черновик», плашки передачи нет (СЦ-8)", async () => {
    seed({}, false);
    const card = await openCard("registrar@demo.example");

    expect(card.getByText("Черновик")).toBeVisible();
    expect(card.queryByText("На подписи")).toBeNull();
    expect(card.queryByText(/Передано на подпись:/)).toBeNull();
  });

  it("адресат текстом из писем до СУЩ-2.6: просьба сопоставить, регистрация закрыта", async () => {
    seed({
      recipient: { name: "ГНИ Мирабадского района", inn: null, company_id: null, contact_id: null },
    });
    const card = await openCard("registrar@demo.example");

    expect(card.getByText(/Адресат вписан текстом/)).toBeVisible();
    expect(card.queryByRole("button", { name: /Зарегистрировать/ })).toBeNull();
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
    expect(card.getByText("PDF с исходящим номером готов · 1 стр.")).toBeVisible();
    fireEvent.click(card.getByRole("button", { name: "Отправить адресату ещё раз" }));
    expect(await screen.findByText("Отправка запрошена")).toBeVisible();
    await waitFor(() => {
      expect(readEds().documents.find((d) => d.id === ID)?.letter?.mailings).toHaveLength(2);
    });
  });

  it("автор без права регистрировать: «Передать на подпись», кнопки регистрации нет", async () => {
    seed({});
    const state = readEds();
    const doc = state.documents.find((d) => d.id === ID);
    if (doc?.letter) doc.letter.registration_requested = null;
    writeEds(state);
    const card = await openCard("universal@demo.example");

    expect(card.queryByRole("button", { name: "Зарегистрировать и отправить" })).toBeNull();
    fireEvent.click(card.getByRole("button", { name: "Передать на подпись" }));
    expect(await screen.findByText("Передано на подпись.")).toBeVisible();
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

    expect(await screen.findByText(/Письмо подписано: OUT-\d{3}\/26/)).toBeVisible();
    const saved = readEds().documents.find((d) => d.id === ID);
    expect(saved?.status).toBe("sent");
    expect(saved?.signed_at).not.toBeNull();
    expect(saved?.verification_code).toMatch(/^RT-26-/);
  });

  it("подписать некому: вместо «Подписать» — подсказка, ссылка на права подписи только у администратора", async () => {
    seed({ signing: { can_sign: false, reason: "no_authority", signer_id: null } });
    const director = await openCard("director@demo.example");
    expect(director.queryByRole("button", { name: "Подписать" })).toBeNull();
    expect(director.getByText(/Подписать некому — полномочие выдаёт администратор/)).toBeVisible();
    expect(director.queryByRole("link", { name: "Настройки · Права подписи" })).toBeNull();
  });

  it("подписать некому у администратора: есть ссылка «Настройки · Права подписи»", async () => {
    seed({
      ownerId: "u-demo-admin",
      signing: { can_sign: false, reason: "no_authority", signer_id: null },
    });
    const admin = await openCard("admin@demo.example");
    const link = admin.getByRole("link", { name: "Настройки · Права подписи" });
    expect(link).toHaveAttribute("href", "/admin/signing");
  });

  it("подписант известен, причина без особой фразы: «Подпишет: имя», кнопки «Подписать» нет", async () => {
    seed(
      { signing: { can_sign: false, reason: "no_permission", signer_id: "u-demo-director" } },
      false,
    );
    const card = await openCard("universal@demo.example");
    expect(card.queryByRole("button", { name: "Подписать" })).toBeNull();
    expect(card.getByText(/Подпишет: /)).toBeVisible();
    expect(card.queryByText(/Подписать некому/)).toBeNull();
  });

  describe("ГЛ-0: письмо на подписи без тупика", () => {
    const director = {
      can_sign: false,
      reason: "author_cannot_sign",
      signer_id: "u-demo-director",
      signer_position: "Директор",
    };

    it("автор видит, у кого письмо и с какого дня; строгий режим объясняет отказ целым предложением", async () => {
      seed({ signing: director });
      const card = await openCard("universal@demo.example");

      expect(card.getByText(/На подписи у Демо Директоров, Директор с /)).toBeVisible();
      expect(
        card.getByText(
          "Вы автор письма. В компании включено правило: автор не подписывает своё письмо. Подписать может Демо Директоров.",
        ),
      ).toBeVisible();
      expect(card.queryByRole("button", { name: /Подписать/ })).toBeNull();
      expect(card.getByRole("button", { name: "Напомнить" })).toBeEnabled();
      expect(card.getByRole("button", { name: "Отозвать" })).toBeEnabled();
      expect(card.getByRole("button", { name: "Сменить подписанта" })).toBeEnabled();
    });

    it("автор вправе подписать сам: «Подписать самому» рядом с действиями над передачей", async () => {
      seed({ signing: { ...director, can_sign: true, reason: null } });
      const card = await openCard("universal@demo.example");

      expect(card.getByRole("button", { name: "Подписать самому" })).toBeVisible();
      expect(card.queryByText(/Вы автор письма/)).toBeNull();
      expect(card.getByText(/На подписи у Демо Директоров/)).toBeVisible();
    });

    it("подписывает сам автор: «Подписываете вы», напоминать некому", async () => {
      seed({
        signing: { can_sign: true, reason: null, signer_id: "u-demo-universal" },
      });
      const card = await openCard("universal@demo.example");

      expect(card.getByText(/Подписываете вы/)).toBeVisible();
      expect(card.getByRole("button", { name: "Подписать" })).toBeVisible();
      expect(card.getByRole("button", { name: "Напомнить" })).toBeDisabled();
    });

    it("«Напомнить» — раз в час: второй раз сервер отказывает, причина словами", async () => {
      seed({ signing: director });
      const card = await openCard("universal@demo.example");

      fireEvent.click(card.getByRole("button", { name: "Напомнить" }));
      expect(await screen.findByText("Напоминание отправлено: Демо Директоров")).toBeVisible();
      expect(readEds().documents.find((d) => d.id === ID)?.letter?.remindedAt).toBeTruthy();
      const again = within(await panelEl());
      // кнопка ещё уходит из состояния «загрузка»: имя с иконкой, поэтому по части имени
      fireEvent.click(await again.findByRole("button", { name: /Напомнить/ }));
      expect(
        await again.findByText(/напоминание уже отправлено, повторить можно через час/),
      ).toBeVisible();
    });

    it("«Отозвать» снимает передачу: «На подписи» гаснет, возвращается «Передать на подпись»", async () => {
      seed({ signing: director });
      const card = await openCard("universal@demo.example");

      fireEvent.click(card.getByRole("button", { name: "Отозвать" }));
      expect(await screen.findByText("Письмо отозвано с подписи")).toBeVisible();
      await waitFor(() => {
        expect(
          readEds().documents.find((d) => d.id === ID)?.letter?.registration_requested,
        ).toBeNull();
      });
      expect(await card.findByRole("button", { name: "Передать на подпись" })).toBeVisible();
      expect(card.queryByRole("button", { name: "Отозвать" })).toBeNull();
      expect(card.queryByText(/На подписи у /)).toBeNull();
    });

    it("«Сменить подписанта»: список подписантов, новый подписант на карточке", async () => {
      seed({ signing: director });
      const card = await openCard("universal@demo.example");

      fireEvent.click(card.getByRole("button", { name: "Сменить подписанта" }));
      const dialog = await findModal("Кто подпишет письмо");
      const box = within(dialog).getByRole("combobox");
      fireEvent.mouseDown(box);
      // список подписантов приходит с сервера: выбираем, пока строка не станет выбранной
      await waitFor(() => {
        const pick = screen.getByTitle("Демо Админов");
        fireEvent.click(pick.closest(".ant-select-item-option") ?? pick);
        expect(within(dialog).getByRole("button", { name: "Сменить" })).toBeEnabled();
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Сменить" }));
      expect(await screen.findByText("Подписант сменён")).toBeVisible();
      await waitFor(() => {
        expect(
          readEds().documents.find((d) => d.id === ID)?.letter?.signer_crm_user_id,
        ).toBeGreaterThanOrEqual(100);
      });
    });

    it("подписанту (не автору) действий над передачей не показываются", async () => {
      seed({ signing: { ...director, can_sign: true, reason: null } });
      const card = await openCard("director@demo.example");

      expect(card.getByRole("button", { name: "Подписать" })).toBeVisible();
      expect(card.queryByRole("button", { name: "Напомнить" })).toBeNull();
      expect(card.queryByRole("button", { name: "Отозвать" })).toBeNull();
      expect(card.queryByRole("button", { name: "Сменить подписанта" })).toBeNull();
    });
  });
});
