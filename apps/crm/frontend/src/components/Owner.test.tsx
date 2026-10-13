import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { whoLeads } from "../domain/owner";
import { Owner } from "./Owner";

const NOW = new Date("2026-10-12T10:00:00Z");
const handoff = (status: string) => ({ status, created_at: "2026-10-12T09:48:00Z" });

describe("whoLeads («Кто ведёт»)", () => {
  it.each([
    ["bot", { owner_mode: "bot", assigned_user_name: "Азиз" }, "bot", "Бот"],
    ["paused", { owner_mode: "paused", assigned_user_name: null }, "paused", "Бот на паузе"],
    ["human", { owner_mode: "human", assigned_user_name: "Азиз" }, "human", "Азиз"],
    ["human без имени", { owner_mode: "human", assigned_user_name: null }, "human", "Менеджер"],
    [
      "open handoff",
      { owner_mode: "bot", assigned_user_name: "Азиз", escalation: handoff("open") },
      "waiting",
      "Ждёт менеджера · 12 мин",
    ],
    [
      "snoozed handoff",
      { owner_mode: "paused", assigned_user_name: null, escalation: handoff("snoozed") },
      "waiting",
      "Ждёт менеджера · 12 мин",
    ],
    [
      "taken handoff",
      { owner_mode: "human", assigned_user_name: "Азиз", escalation: handoff("taken") },
      "human",
      "Азиз",
    ],
  ])("%s", (_name, lead, kind, label) => {
    const who = whoLeads(lead, NOW);
    expect(who.kind).toBe(kind);
    expect(who.label.replace(/\u00a0/g, " ")).toBe(label);
  });
});

describe("Owner", () => {
  it("never shows the bot mode next to a manager name", () => {
    render(<Owner lead={{ owner_mode: "bot", assigned_user_name: "Азиз" }} />);
    expect(screen.getByText("Бот")).toBeInTheDocument();
    expect(screen.queryByText("Азиз")).not.toBeInTheDocument();
  });
});
