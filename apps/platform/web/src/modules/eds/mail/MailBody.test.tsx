import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { resetInboundMailMock } from "../../../mocks/inboundMail";
import type { InboundMailMessage } from "../../../shared/api/generated/model";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";
import { renderUi } from "../../../test/renderUi";
import { MailBody, PREVIEW_LINES } from "./MailBody";
import { MailHtml } from "./MailHtml";

setupLetterTests();
beforeEach(() => {
  resetInboundMailMock();
});

const REGISTRAR = "registrar@demo.example";
const REMOTE = "https://cdn.example.test/banner.png";

function message(over: Partial<InboundMailMessage> = {}): InboundMailMessage {
  return {
    id: 1,
    from_email: "a@example.test",
    from_name: "Демо",
    at: "2026-11-03T05:00:00Z",
    text: "Короткое письмо",
    text_tail: "",
    html: null,
    html_remote_images: 0,
    attachments: [],
    new_participant: false,
    ...over,
  };
}

function frame(): HTMLIFrameElement {
  const el = document.querySelector("iframe");
  if (!el) throw new Error("нет iframe");
  return el;
}

describe("HTML письма: фрейм, sandbox, CSP, картинки (P2-4)", () => {
  const html = `<p>Привет</p><img data-rt-src="${REMOTE}" width="1" height="1" alt="">`;

  it("sandbox без allow-scripts, srcdoc со строгим CSP, внешний адрес в разметку не попадает до клика", () => {
    renderUi(<MailHtml html={html} remoteImages={1} subject="Рассылка" />);
    const el = frame();
    const sandbox = (el.getAttribute("sandbox") ?? "").split(" ");
    expect(sandbox).not.toContain("allow-scripts");
    expect(sandbox).toContain("allow-popups");
    expect(el).toHaveAccessibleName("Письмо «Рассылка»");
    const doc = el.getAttribute("srcdoc") ?? "";
    expect(doc).toContain('http-equiv="Content-Security-Policy"');
    expect(doc).toContain("default-src 'none'");
    expect(doc).toContain("img-src data:;");
    expect(doc).not.toContain("cdn.example.test");
    expect(doc).not.toMatch(/<img[^>]*\ssrc=/);
  });

  it("«Показать картинки» подставляет адреса и расширяет CSP; кнопка исчезает", () => {
    renderUi(<MailHtml html={html} remoteImages={1} subject="Рассылка" />);
    fireEvent.click(screen.getByRole("button", { name: "Показать картинки (1)" }));
    const doc = frame().getAttribute("srcdoc") ?? "";
    expect(doc).toContain(`src="${REMOTE}"`);
    expect(doc).toContain("img-src data: https:;");
    expect(screen.queryByRole("button", { name: /Показать картинки/ })).toBeNull();
    expect(frame().getAttribute("sandbox")).not.toContain("allow-scripts");
  });

  it("нет внешних картинок — нет и кнопки", () => {
    renderUi(<MailHtml html="<p>Только текст</p>" remoteImages={0} subject="Письмо" />);
    expect(screen.queryByRole("button", { name: /Показать картинки/ })).toBeNull();
    expect(screen.queryByText("Внешние картинки не загружены")).toBeNull();
  });

  it("фрейм не прокручивается сам: высота задаётся по содержимому, а не фиксируется", () => {
    renderUi(<MailHtml html="<p>Текст</p>" remoteImages={0} subject="Письмо" />);
    expect(frame().style.height).not.toBe("");
    expect(frame().getAttribute("scrolling")).toBeNull();
    expect(frame().getAttribute("srcdoc")).toContain("overflow:hidden");
  });
});

describe("Тело письма: превью, «…» и «Открыть письмо полностью» (P2-4)", () => {
  const long = Array.from({ length: 20 }, (_, i) => `Строка ${String(i + 1)}`).join("\n");

  it("длинный текст — только первые строки и кнопка «Открыть письмо полностью»; в шторке — всё письмо", async () => {
    renderUi(<MailBody message={message({ text: long })} subject="Длинное" />);
    expect(screen.getByText(/Строка 1\b/)).toBeVisible();
    expect(screen.getByText(new RegExp(`Строка ${String(PREVIEW_LINES)}$`))).toBeVisible();
    expect(screen.queryByText(/Строка 9$/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Открыть письмо полностью" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Строка 20$/)).toBeVisible();
  });

  it("короткое письмо без HTML — без кнопки", () => {
    renderUi(<MailBody message={message()} subject="Коротко" />);
    expect(screen.getByText("Короткое письмо")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Открыть письмо полностью" })).toBeNull();
  });

  it("цитата и подпись свёрнуты под «…» и раскрываются по клику", () => {
    renderUi(
      <MailBody message={message({ text_tail: "Иван пишет:\n> старый текст" })} subject="Ответ" />,
    );
    expect(screen.queryByText(/старый текст/)).toBeNull();
    const toggle = screen.getByRole("button", { name: "Показать цитату и подпись" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByText(/старый текст/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Скрыть цитату и подпись" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("письмо с HTML открывается во фрейме в шторке, превью остаётся текстом", async () => {
    renderUi(
      <MailBody
        message={message({ html: "<p>Красивое письмо</p>", html_remote_images: 0 })}
        subject="Рассылка"
      />,
    );
    expect(document.querySelector("iframe")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Открыть письмо полностью" }));
    await waitFor(() => {
      expect(document.querySelector("iframe")).not.toBeNull();
    });
    expect(frame().getAttribute("srcdoc")).toContain("Красивое письмо");
  });
});

describe("Карточка письма-рассылки и ответа с цитатой (P2-4)", () => {
  it("рассылка: логотип из тела не в списке вложений, внешние картинки только по кнопке", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/19");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Скидки недели на канцтовары" }),
    ).toBeVisible();
    expect(screen.queryByText("logo.png")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Открыть письмо полностью" }));
    const dialog = await screen.findByRole("dialog");
    const el = within(dialog).getByTitle("Письмо «Скидки недели на канцтовары»");
    const doc = el.getAttribute("srcdoc") ?? "";
    expect(doc).not.toContain("cdn.promo-demo.example");
    expect(doc).not.toContain("track.promo-demo.example");
    expect(doc).not.toMatch(/<img[^>]*data-rt-src/);
    expect(doc).toContain("rt-missing");
    expect(doc).toContain("<details");
    fireEvent.click(within(dialog).getByRole("button", { name: "Показать картинки (2)" }));
    expect(el.getAttribute("srcdoc")).toContain('src="https://cdn.promo-demo.example/banner.png"');
  });

  it("ответ с цитатой: в карточке только новый текст, цитата и подпись — под «…»", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/21");
    expect(await screen.findByText(/Выставляем счёт на смазку/)).toBeVisible();
    expect(screen.queryByText(/Подскажите цену смазки/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Показать цитату и подпись" }));
    expect(screen.getByText(/Подскажите цену смазки/)).toBeVisible();
    expect(screen.getByText(/Демо-Масла, отдел продаж/)).toBeVisible();
  });
});
