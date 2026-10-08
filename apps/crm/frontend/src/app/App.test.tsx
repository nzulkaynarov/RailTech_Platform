import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([
    { ok: true, expected: "ok" },
    { ok: false, expected: "unavailable" },
  ])("shows API health = $expected", async ({ ok, expected }) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok }));
    render(<App />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it("shows unavailable when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    render(<App />);
    expect(await screen.findByText("unavailable")).toBeInTheDocument();
  });
});
