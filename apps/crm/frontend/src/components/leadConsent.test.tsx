import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LeadDetail } from "../api/generated/model";
import { LeadActions } from "./LeadActions";
import {
  type ActionRights,
  availableActions,
  leadActionPlan,
  mayRecordConsent,
} from "./leadActionRules";

const recordConsent = vi.fn();
vi.mock("../api/generated/crm", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/generated/crm")>()),
  recordConsent: (...args: unknown[]) => recordConsent(...args) as unknown,
}));

// Лид из звонка: заведён вручную, согласия нет, ведёт менеджер 7, режим ERP (D-8).
const lead = (patch: Partial<LeadDetail> = {}): LeadDetail => ({
  id: 5,
  display_name: "Клиент по звонку",
  language: "ru",
  stage: "in_progress",
  score: 0,
  owner_mode: "human",
  assigned_user_id: 7,
  need_summary: null,
  product_interest: [],
  last_lead_msg_at: null,
  created_at: "2026-10-20T10:00:00Z",
  escalation: null,
  qualification: {},
  consent_given_at: null,
  tg_username: null,
  notes_count: 0,
  snoozed_until: null,
  source: "phone",
  backoffice_mode: "erp",
  ...patch,
});

const manager: ActionRights = {
  take: true,
  work: true,
  note: true,
  reply: true,
  clients: true,
  userId: 7,
  isAdmin: false,
};

describe("«Согласие получено» — кто и когда видит действие (зеркало бэкенда)", () => {
  it.each([
    ["звонок без согласия", lead(), manager, true],
    ["письмо", lead({ source: "email" }), manager, true],
    ["рекомендация", lead({ source: "referral" }), manager, true],
    ["лид из Telegram: согласие — в боте", lead({ source: "telegram" }), manager, false],
    ["форма сайта: согласие уже дано формой", lead({ source: "web" }), manager, false],
    ["согласие уже есть", lead({ consent_given_at: "2026-10-20T11:00:00Z" }), manager, false],
    ["нет права на клиентов", lead(), { ...manager, clients: false }, false],
    ["чужой лид", lead({ assigned_user_id: 3 }), manager, false],
    ["чужой лид, админ", lead({ assigned_user_id: 3 }), { ...manager, isAdmin: true }, true],
    ["лид без ответственного", lead({ assigned_user_id: null, owner_mode: "bot" }), manager, true],
  ] as const)("%s → %s", (_, item, rights, expected) => {
    expect(mayRecordConsent(item, rights)).toBe(expected);
    expect(availableActions(item, rights).recordConsent).toBe(expected);
  });

  it("в режиме ERP без согласия это главное действие: передача без него даёт 422", () => {
    const plan = leadActionPlan(lead(), manager);
    expect(plan.primary).toBe("recordConsent");
    expect(plan.more).toContain("makeCustomer");
  });

  it("после отметки главным снова становится «Передать в бэк-офис»", () => {
    const plan = leadActionPlan(lead({ consent_given_at: "2026-10-20T11:00:00Z" }), manager);
    expect(plan.primary).toBe("makeCustomer");
    expect(plan.more).not.toContain("recordConsent");
  });

  it("без ERP главное действие прежнее, а отметка — в «Ещё»", () => {
    const plan = leadActionPlan(lead({ backoffice_mode: "local", stage: "won" }), manager);
    expect(plan.primary).toBe("makeCustomer");
    expect(plan.more).toContain("recordConsent");
  });
});

function show(item: LeadDetail, rights: ActionRights = manager) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AntApp>
          <LeadActions lead={item} rights={rights} />
        </AntApp>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Кнопка подтверждения в диалоге (одноимённая с кнопкой действия на карточке). */
const confirm = () => {
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Согласие получено" }),
  );
};

beforeEach(() => {
  recordConsent.mockReset().mockResolvedValue({ ok: true, recorded: true });
});

describe("LeadActions — «Согласие получено»", () => {
  it("диалог: способ и комментарий уходят на бэкенд", async () => {
    show(lead());
    fireEvent.click(screen.getByRole("button", { name: "Согласие получено" }));
    await screen.findByRole("dialog");
    expect(screen.getByRole("radiogroup", { name: "Как получено согласие" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Письмом" }));
    fireEvent.change(screen.getByLabelText("Комментарий (необязательно)"), {
      target: { value: "  Письмо от 20.10  " },
    });
    confirm();
    await waitFor(() => {
      expect(recordConsent).toHaveBeenCalledWith(5, {
        method: "email",
        comment: "Письмо от 20.10",
      });
    });
  });

  it("по умолчанию — устно по телефону, пустой комментарий уходит как null", async () => {
    show(lead());
    fireEvent.click(screen.getByRole("button", { name: "Согласие получено" }));
    await screen.findByRole("dialog");
    confirm();
    await waitFor(() => {
      expect(recordConsent).toHaveBeenCalledWith(5, { method: "phone", comment: null });
    });
  });

  it("кнопки нет у лида из Telegram и без права на клиентов", () => {
    show(lead({ source: "telegram" }));
    expect(screen.queryByRole("button", { name: "Согласие получено" })).toBeNull();
    show(lead(), { ...manager, clients: false });
    expect(screen.queryByRole("button", { name: "Согласие получено" })).toBeNull();
  });
});
