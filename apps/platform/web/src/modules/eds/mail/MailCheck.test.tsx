import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MOCK_IMAP_OFF_KEY,
  MOCK_MAIL_CHECK_KEY,
  resetInboundMailMock,
} from "../../../mocks/inboundMail";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";

setupLetterTests();
beforeEach(() => {
  resetInboundMailMock();
});

const REGISTRAR = "registrar@demo.example";
const NEW_LETTER = "Срочно: подтвердите наличие шпал на этой неделе";

async function open() {
  signIn(REGISTRAR);
  renderAt("/eds/mail");
  await screen.findByRole("list", { name: "Письма, ждущие разбора" });
  return screen.getByRole("button", { name: "Проверить почту" });
}

afterEach(() => {
  vi.useRealTimers();
});

const status = () => screen.getByRole("status", { name: "Итог проверки почты" });

describe("Входящая почта: «Проверить почту» (MAIL-NOW)", () => {
  it("рядом с кнопкой — когда была последняя проверка", async () => {
    await open();
    expect(screen.getByText("Проверено 2 мин назад")).toBeVisible();
  });

  it("проверка приносит письмо: сообщение «Новых писем: 1», список обновился сам, время — «только что»", async () => {
    const button = await open();
    expect(screen.queryByText(NEW_LETTER)).toBeNull();
    fireEvent.click(button);
    expect(await screen.findByText("Новых писем: 1")).toBeVisible();
    expect(await screen.findByText(NEW_LETTER)).toBeVisible();
    await waitFor(() => {
      expect(screen.getByText("Проверено только что")).toBeVisible();
    });
    expect(status()).toHaveTextContent("Новых писем: 1");
  });

  it("пока идёт проверка — кнопка занята и сообщает об этом", async () => {
    const button = await open();
    fireEvent.click(button);
    const busy = await screen.findByRole("button", { name: "Проверяю…" });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    await screen.findByText("Новых писем: 1");
    expect(screen.getByRole("button", { name: "Проверить почту" })).toBeEnabled();
  });

  it("повторное нажатие раньше 20 секунд — «Можно проверить ещё раз через N с», новых писем не прибавилось", async () => {
    const button = await open();
    fireEvent.click(button);
    await screen.findByText("Новых писем: 1");
    fireEvent.click(await screen.findByRole("button", { name: "Проверить почту" }));
    await waitFor(() => {
      expect(status()).toHaveTextContent(/^Можно проверить ещё раз через \d+ с$/);
    });
    const list = screen.getByRole("list", { name: "Письма, ждущие разбора" });
    expect(within(list).getAllByText(NEW_LETTER)).toHaveLength(1);
  });

  it("новых писем нет", async () => {
    window.localStorage.setItem(MOCK_MAIL_CHECK_KEY, "none");
    fireEvent.click(await open());
    expect(await screen.findByText("Новых писем нет")).toBeVisible();
  });

  it("почтовый сервер недоступен — «Не удалось подключиться к почтовому серверу»", async () => {
    window.localStorage.setItem(MOCK_MAIL_CHECK_KEY, "error");
    fireEvent.click(await open());
    expect(await screen.findByText("Не удалось подключиться к почтовому серверу")).toBeVisible();
  });

  it("сервер не принял пароль — отдельная фраза и подсказка, где исправить", async () => {
    window.localStorage.setItem(MOCK_MAIL_CHECK_KEY, "auth");
    fireEvent.click(await open());
    await waitFor(() => {
      expect(status()).toHaveTextContent(
        "Почтовый сервер не принял логин или пароль — Настройки · Почта",
      );
    });
  });

  it("проверка продолжается в фоне — письма появятся в списке сами", async () => {
    window.localStorage.setItem(MOCK_MAIL_CHECK_KEY, "checking");
    fireEvent.click(await open());
    expect(await screen.findByText("Проверка идёт — письма появятся в списке сами")).toBeVisible();
  });

  it("почта не настроена — «Почта не настроена — Настройки · Почта»", async () => {
    window.localStorage.setItem(MOCK_IMAP_OFF_KEY, "1");
    signIn(REGISTRAR);
    renderAt("/eds/mail");
    fireEvent.click(await screen.findByRole("button", { name: "Проверить почту" }));
    await waitFor(() => {
      expect(status()).toHaveTextContent("Почта не настроена — Настройки · Почта");
    });
  });

  it("сотруднику без первой линии кнопки нет: он видит только свои письма", async () => {
    signIn("universal@demo.example");
    renderAt("/eds/my-mail");
    await screen.findByRole("list", { name: /./ });
    expect(screen.queryByRole("button", { name: "Проверить почту" })).toBeNull();
  });

  it("письмо от планового опроса появляется в списке само — раз в минуту, без нажатия", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    await open();
    expect(screen.queryByText(NEW_LETTER)).toBeNull();
    // Письмо пришло на сервер между перечитываниями списка (плановый опрос CRM).
    await fetch("http://localhost/api/v1/inbound-mail/poll", { method: "POST" });
    await vi.advanceTimersByTimeAsync(61_000);
    vi.useRealTimers();
    expect(await screen.findByText(NEW_LETTER)).toBeVisible();
  });
});
