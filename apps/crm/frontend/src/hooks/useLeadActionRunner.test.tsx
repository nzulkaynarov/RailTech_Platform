import { fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/http";
import { doneText, useTakeAndOpen } from "./useLeadActionRunner";

const mutateAsync = vi.fn();
vi.mock("../api/queries", () => ({
  useLeadAction: () => ({ mutateAsync, isPending: false }),
}));

function Take() {
  const { takeAndOpen } = useTakeAndOpen(11);
  return (
    <button type="button" onClick={() => void takeAndOpen()}>
      take
    </button>
  );
}

const renderInbox = () =>
  render(
    <MemoryRouter initialEntries={["/inbox"]}>
      <AntApp>
        <Routes>
          <Route path="/inbox" element={<Take />} />
          <Route path="/leads/:id" element={<p>lead card</p>} />
        </Routes>
      </AntApp>
    </MemoryRouter>,
  );

describe("useTakeAndOpen", () => {
  beforeEach(() => {
    mutateAsync.mockReset();
  });

  it("opens the lead card right after a successful take", async () => {
    mutateAsync.mockResolvedValue(undefined);
    renderInbox();
    fireEvent.click(screen.getByRole("button", { name: "take" }));
    expect(await screen.findByText("lead card")).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledWith({ kind: "take" });
  });

  it("stays in the inbox and explains the error when the take fails", async () => {
    mutateAsync.mockRejectedValue(new ApiError(403, "forbidden", "no"));
    renderInbox();
    fireEvent.click(screen.getByRole("button", { name: "take" }));
    expect(await screen.findByText("Недостаточно прав")).toBeInTheDocument();
    expect(screen.queryByText("lead card")).toBeNull();
  });
});

describe("doneText", () => {
  it.each([
    [{ kind: "take" } as const, "Лид ваш"],
    [{ kind: "won", reason: null, amount: null } as const, "Сделка закрыта"],
    [{ kind: "reply", text: "x" } as const, "Готово"],
  ])("%j → %s", (action, text) => {
    expect(doneText(action)).toBe(text);
  });
});
