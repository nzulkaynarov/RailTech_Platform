import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Owner } from "./Owner";

describe("Owner", () => {
  it("shows the person when a manager leads the lead", () => {
    render(<Owner lead={{ owner_mode: "human", assigned_user_name: "Азиз" }} />);
    expect(screen.getByText("Азиз")).toBeInTheDocument();
    expect(screen.queryByText("Ведёт бот")).not.toBeInTheDocument();
  });

  it("keeps the responsible person and marks the bot mode as a tag", () => {
    render(<Owner lead={{ owner_mode: "bot", assigned_user_name: "Азиз" }} />);
    expect(screen.getByText("Азиз")).toBeInTheDocument();
    expect(screen.getByText("Ведёт бот")).toBeInTheDocument();
  });

  it("shows only the mode when nobody is responsible", () => {
    render(<Owner lead={{ owner_mode: "paused", assigned_user_name: null }} />);
    expect(screen.getByText("Бот на паузе")).toBeInTheDocument();
  });
});
