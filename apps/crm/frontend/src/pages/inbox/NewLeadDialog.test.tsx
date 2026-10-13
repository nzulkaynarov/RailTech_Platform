import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/http";
import { NewLeadDialog } from "./NewLeadDialog";

const { createLead, navigate } = vi.hoisted(() => ({ createLead: vi.fn(), navigate: vi.fn() }));

vi.mock("../../api/generated/crm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/generated/crm")>();
  return { ...actual, createLead };
});
vi.mock("react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router")>();
  return { ...actual, useNavigate: () => navigate };
});

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <AntApp>
        <MemoryRouter>{children}</MemoryRouter>
      </AntApp>
    </QueryClientProvider>
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("NewLeadDialog", () => {
  beforeEach(() => {
    createLead.mockReset();
    navigate.mockReset();
  });

  it("creates a lead from a call and opens its card", async () => {
    createLead.mockResolvedValue({ id: 42 });
    const onClose = vi.fn();
    render(wrap(<NewLeadDialog open onClose={onClose} />));
    fill("Имя", " Бобур ");
    fill("Компания", "Logistics LLC");
    fill("Телефон", "90 765 43 21");
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(createLead).toHaveBeenCalledWith({
        source: "phone",
        name: "Бобур",
        company: "Logistics LLC",
        phone: "90 765 43 21",
        email: null,
        need: null,
        language: "ru",
      });
    });
    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith("/leads/42");
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("requires a phone for a call and does not call the API", async () => {
    render(wrap(<NewLeadDialog open onClose={vi.fn()} />));
    fill("Имя", "Бобур");
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    expect(await screen.findByText("Для звонка нужен телефон")).toBeInTheDocument();
    expect(createLead).not.toHaveBeenCalled();
  });

  it("offers the existing lead on 409 lead_exists instead of duplicating", async () => {
    createLead.mockRejectedValue(
      new ApiError(409, "conflict", "exists", {
        reason: "lead_exists",
        lead_id: 7,
        display_name: "Алишер",
        field: "phone",
      }),
    );
    render(wrap(<NewLeadDialog open onClose={vi.fn()} />));
    fill("Имя", "Бобур");
    fill("Телефон", "+998901234567");
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    const link = await screen.findByRole("link", { name: "Открыть лида" });
    expect(link).toHaveAttribute("href", "/leads/7");
    expect(screen.getByText(/Алишер/)).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("highlights the phone field on invalid_phone", async () => {
    createLead.mockRejectedValue(
      new ApiError(422, "validation_failed", "bad", { reason: "invalid_phone", field: "phone" }),
    );
    render(wrap(<NewLeadDialog open onClose={vi.fn()} />));
    fill("Имя", "Бобур");
    fill("Телефон", "abc");
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    expect(await screen.findByText(/кодом страны/)).toBeInTheDocument();
  });
});
