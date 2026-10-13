import { Refine } from "@refinedev/core";
import routerProvider, { UnsavedChangesNotifier } from "@refinedev/react-router";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Link, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { i18nProvider } from "../app/providers/i18n";
import { t } from "../i18n/ru";
import { useDirtyForms } from "./useDirtyForms";

const STEPS = [
  ["company", true],
  ["business_hours", true],
  ["company", false],
  ["business_hours", false],
] as const;

/** Две формы мастера: кнопки сообщают «изменена / сохранена», ссылка уводит со страницы. */
function TwoForms() {
  const report = useDirtyForms();
  return (
    <>
      {STEPS.map(([key, dirty]) => (
        <button
          key={`${key}-${String(dirty)}`}
          type="button"
          onClick={() => {
            report(key, dirty);
          }}
        >
          {`${key} ${dirty ? "dirty" : "saved"}`}
        </button>
      ))}
      <Link to="/away">away</Link>
    </>
  );
}

function renderApp() {
  render(
    <MemoryRouter initialEntries={["/setup"]}>
      <Refine
        routerProvider={routerProvider}
        i18nProvider={i18nProvider}
        options={{ warnWhenUnsavedChanges: true, disableTelemetry: true }}
      >
        <UnsavedChangesNotifier />
        <Routes>
          <Route path="/setup" element={<TwoForms />} />
          <Route path="/away" element={<p>left</p>} />
        </Routes>
      </Refine>
    </MemoryRouter>,
  );
}

const click = (name: string) => {
  fireEvent.click(screen.getByRole("button", { name }));
};

const leave = () => {
  fireEvent.click(screen.getByRole("link", { name: "away" }));
};

describe("unsaved changes (Refine UnsavedChangesNotifier)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("asks in Russian before leaving while any form is dirty", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderApp();
    click("company dirty");
    click("business_hours dirty");
    click("company saved");
    leave();
    expect(confirm).toHaveBeenCalledWith(t.unsaved.leave);
    expect(screen.queryByText("left")).toBeNull();
  });

  it("leaves without asking once every form is saved", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderApp();
    click("company dirty");
    click("business_hours dirty");
    click("company saved");
    click("business_hours saved");
    leave();
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.getByText("left")).toBeTruthy();
  });
});
