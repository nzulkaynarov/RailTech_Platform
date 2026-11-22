import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { readLetters, resetLetters, writeLetters } from "../../../mocks/fixtures/letters";
import i18n from "../../../shared/i18n";
import { renderAt, signIn } from "../../../test/lettersKit";
import { openSideTab } from "../../../test/panel";
import { setViewportWidth } from "../../../test/viewport";
import { usePanelsStore } from "../../../app/shell/panelsStore";
import { endSession } from "../../../mocks/mockSession";

// Own setup (not `setupLetterTests`): this test feeds a code the dictionary does not know on purpose.
beforeEach(() => {
  window.localStorage.clear();
  resetLetters();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  cleanup();
  endSession();
});

describe("СЦ-7: история письма", () => {
  it("слово на каждое действие; код, которого словарь не знает, не показывается", async () => {
    writeLetters(
      readLetters().map((letter) =>
        letter.number === "ВХ-104/26"
          ? {
              ...letter,
              journal: [
                ...letter.journal,
                { at: "2026-10-29T11:00:00Z", action: "file.attached", by: null, comment: null },
                {
                  at: "2026-10-29T12:00:00Z",
                  action: "letter.future_step",
                  by: null,
                  comment: null,
                },
              ],
            }
          : letter,
      ),
    );
    signIn("director@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-104%2F26");

    await screen.findByRole("heading", { level: 1, name: "Письмо ВХ-104/26" });
    const journal = await openSideTab("История");
    expect(within(journal).getByText("Приложен файл")).toBeVisible();
    expect(within(journal).getByText("Действие в письме")).toBeVisible();
    expect(journal.textContent).not.toContain("letter.future_step");
    expect(journal.textContent).not.toContain("file.attached");
  });
});
