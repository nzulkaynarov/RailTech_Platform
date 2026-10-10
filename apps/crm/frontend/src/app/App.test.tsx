import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("redirects anonymous users to the login page", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    render(<App />);
    expect(await screen.findByText("Вход в CRM")).toBeInTheDocument();
  });

  it("login page has a main landmark, an h1 and a document title", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    render(<App />);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Вход в CRM" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.title).toBe("Вход — RailTech CRM");
    });
  });
});
