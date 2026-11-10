import { fireEvent, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";

function queueWith(kind: string, title: string, due: string, label = "later") {
  return {
    id: title,
    role_id: "1",
    kind,
    title,
    subtitle: "",
    due_label: label,
    due_at: due,
    object: { kind: "letter", number: "ВХ-1/26", path: "/eds/inbox" },
  };
}

beforeEach(() => {
  window.localStorage.clear();
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

describe("Органайзер · Календарь", () => {
  it("показывает сроки задач; фильтр скрывает вид; просрочка подписана словом", async () => {
    const now = new Date().toISOString();
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({
          items: [
            queueWith("resolve_letter", "Резолюция на письмо", now),
            queueWith("issue_invoice", "Выставить счёт", now, "overdue"),
          ],
        }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/chats/calendar");

    expect(await screen.findByText("Резолюция на письмо")).toBeVisible();
    expect(screen.getByText("Выставить счёт")).toBeVisible();
    expect(screen.getByText("просрочено")).toBeVisible();

    fireEvent.click(screen.getByRole("checkbox", { name: "Документы" }));
    await waitFor(() => {
      expect(screen.queryByText("Резолюция на письмо")).toBeNull();
    });
    expect(screen.getByText("Выставить счёт")).toBeVisible();
  });
});
