import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DEMO_RESET_TOKEN } from "../../mocks/profileHandlers";
import i18n from "../../shared/i18n";
import { renderApp } from "../../test/renderApp";
import { server } from "../../test/server";

beforeEach(() => {
  window.localStorage.clear();
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  window.localStorage.clear();
});

describe("«Забыли пароль?»", () => {
  it("на экране входа есть ссылка, ведущая к форме", async () => {
    renderApp("/login");
    fireEvent.click(await screen.findByRole("link", { name: "Забыли пароль?" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Забыли пароль?" })).toBeVisible();
    expect(
      screen.getByText(
        /придёт на почту или в Telegram; если нет ни того, ни другого — обратитесь к администратору/,
      ),
    ).toBeVisible();
  });

  it("ответ один и тот же для любого адреса: «Запрос принят», без слов «найден» или «не найден»", async () => {
    const asked: unknown[] = [];
    server.use(
      http.post("*/auth/forgot-password", async ({ request }) => {
        asked.push(await request.json());
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    renderApp("/forgot-password");
    fireEvent.change(await screen.findByLabelText("Электронная почта"), {
      target: { value: "nobody@demo.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Прислать ссылку/ }));

    const note = await screen.findByRole("status");
    expect(note).toHaveTextContent("Запрос принят");
    expect(note).toHaveTextContent("обратитесь к администратору");
    expect(note.textContent).not.toMatch(/не найден|нет такой|существует/i);
    expect(asked).toEqual([{ identifier: "nobody@demo.example" }]);
    expect(screen.getByRole("link", { name: "Вернуться ко входу" })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  it("лимит запросов — словами", async () => {
    renderApp("/forgot-password");
    fireEvent.change(await screen.findByLabelText("Электронная почта"), {
      target: { value: "limit@demo.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Прислать ссылку/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Слишком много запросов");
  });

  it("почта проверяется до отправки", async () => {
    renderApp("/forgot-password");
    fireEvent.change(await screen.findByLabelText("Электронная почта"), {
      target: { value: "oops" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Прислать ссылку/ }));
    expect(await screen.findByText("Проверьте адрес электронной почты")).toBeInTheDocument();
  });
});

describe("Новый пароль по ссылке", () => {
  async function submit(token: string, password: string, again = password) {
    renderApp(`/reset-password?token=${token}`);
    fireEvent.change(await screen.findByLabelText("Новый пароль"), { target: { value: password } });
    fireEvent.change(screen.getByLabelText("Повторите пароль"), { target: { value: again } });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить пароль/ }));
  }

  it("успех: вход с подсказкой, что пароль изменён", async () => {
    await submit(DEMO_RESET_TOKEN, "Brand-new-secret-77");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Вход в Платформу" }),
    ).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Пароль изменён. Войдите с новым паролем.",
    );
  });

  it("недействительная ссылка: слова и «Запросить новую ссылку»", async () => {
    await submit("expired-token-0123456789abcdef", "Brand-new-secret-77");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ссылка недействительна или устарела",
    );
    expect(screen.getByRole("link", { name: "Запросить новую ссылку" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("слабый пароль: ссылка остаётся рабочей, форма на месте", async () => {
    await submit(DEMO_RESET_TOKEN, "short1abc");
    expect(await screen.findByRole("alert")).toHaveTextContent("Пароль слишком простой");
    expect(screen.getByRole("button", { name: /Сохранить пароль/ })).toBeVisible();
  });

  it("пароли не совпадают — до отправки", async () => {
    await submit(DEMO_RESET_TOKEN, "Brand-new-secret-77", "Brand-new-secret-78");
    expect(await screen.findByText("Пароли не совпадают")).toBeInTheDocument();
  });

  it("без кода в ссылке — объяснение и путь к новой ссылке", async () => {
    renderApp("/reset-password");
    const main = await screen.findByRole("main");
    await waitFor(() => {
      expect(within(main).getByRole("alert")).toHaveTextContent("В ссылке нет кода");
    });
    expect(within(main).getByRole("link", { name: "Запросить новую ссылку" })).toBeVisible();
  });
});
