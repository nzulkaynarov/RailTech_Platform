import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { QueueNav } from "./QueueNav";

const lead = (id: number) => ({ id, escalation: null });
vi.mock("../api/queries", () => ({
  useInbox: () => ({
    data: { escalations: [], mine: [lead(1), lead(2), lead(3)], unassigned: [] },
  }),
}));

function Card() {
  const id = Number(useParams()["id"]);
  return (
    <>
      <p>lead {id}</p>
      <QueueNav leadId={id} />
      <textarea aria-label="reply" />
    </>
  );
}

const renderAt = (id: number) =>
  render(
    <MemoryRouter initialEntries={[`/leads/${String(id)}`]}>
      <Routes>
        <Route path="/leads/:id" element={<Card />} />
      </Routes>
    </MemoryRouter>,
  );

describe("QueueNav", () => {
  it("shows the position and moves along the inbox queue", () => {
    renderAt(2);
    expect(screen.getByText("2 из 3 во входящих")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Следующий лид" }));
    expect(screen.getByText("lead 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Следующий лид" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Предыдущий лид" }));
    expect(screen.getByText("lead 2")).toBeInTheDocument();
  });

  it("answers J/K outside text fields only", () => {
    renderAt(1);
    fireEvent.keyDown(window, { code: "KeyJ" });
    expect(screen.getByText("lead 2")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText("reply"), { code: "KeyK" });
    expect(screen.getByText("lead 2")).toBeInTheDocument();
    fireEvent.keyDown(window, { code: "KeyK" });
    expect(screen.getByText("lead 1")).toBeInTheDocument();
  });

  it("renders nothing for a lead outside the queue", () => {
    renderAt(9);
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
