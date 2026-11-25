import { fireEvent, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { readLeads, resetLeads } from "../../../mocks/fixtures/leads";
import { resetMessages } from "../../../mocks/fixtures/messages";
import type { PartnerHandoffIn } from "../../../shared/api/generated/model";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";
import { server } from "../../../test/server";

setupBotTests();

beforeEach(() => {
  resetLeads();
  resetMessages();
});

async function openLead(lead: string): Promise<HTMLElement> {
  signIn("manager@demo.example");
  renderAt(`/crm/leads?lead=${lead}&create=1&panel=open&tab=card`);
  return panelEl();
}

describe("«Кто это?» в шаге «Создать заявку» (ЛП-1)", () => {
  it("лид без клиента начинает с «Клиент»: форма заявки клиента на месте", async () => {
    const panel = await openLead("L-2041");
    const who = await within(panel).findByRole("group", { name: "Кто это?" });
    expect(within(who).getByRole("radio", { name: "Клиент" })).toBeChecked();
    expect(within(panel).getByRole("form", { name: "Создать заявку" })).toBeInTheDocument();
  });

  it("лид с партнёрской формы сайта начинает с «Партнёр»; «Клиент» возвращает заявку клиента", async () => {
    const panel = await openLead("L-2044");
    const who = await within(panel).findByRole("group", { name: "Кто это?" });
    expect(within(who).getByRole("radio", { name: "Партнёр" })).toBeChecked();
    expect(await within(panel).findByRole("form", { name: "Партнёр" })).toBeInTheDocument();
    fireEvent.click(within(who).getByRole("radio", { name: "Клиент" }));
    expect(await within(panel).findByRole("form", { name: "Создать заявку" })).toBeInTheDocument();
  });

  it("«Партнёр»: заявка уходит один раз даже при двойном нажатии, лид закрыт исходом, клиентом не стал", async () => {
    const sent: PartnerHandoffIn[] = [];
    server.use(
      http.post("*/api/v1/crm/leads/:lead/partner", async ({ request }) => {
        sent.push((await request.json()) as PartnerHandoffIn);
        return HttpResponse.json(
          { lead: "L-2044", application: 7001, created: true },
          { status: 201 },
        );
      }),
    );
    const panel = await openLead("L-2044");
    const form = await within(panel).findByRole("form", { name: "Партнёр" });
    expect(within(form).getByLabelText("Компания")).toHaveValue("ООО Демо-Строй");
    const submit = within(form).getByRole("button", { name: "Передать как партнёра" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(await within(panel).findByText("Лид передан как партнёр")).toBeInTheDocument();
    await waitFor(() => {
      expect(sent).toHaveLength(1);
    });
    expect(sent[0]).toMatchObject({ company_name: "ООО Демо-Строй", country: "UZ" });
  });

  it("пустые поля не уходят: ошибки у полей, запроса нет", async () => {
    let calls = 0;
    server.use(
      http.post("*/api/v1/crm/leads/:lead/partner", () => {
        calls += 1;
        return HttpResponse.json({ lead: "L-2044", application: 1, created: true });
      }),
    );
    const panel = await openLead("L-2044");
    const form = await within(panel).findByRole("form", { name: "Партнёр" });
    fireEvent.change(within(form).getByLabelText("Компания"), { target: { value: "" } });
    fireEvent.click(within(form).getByRole("button", { name: "Передать как партнёра" }));
    expect(await within(form).findByText("Укажите компанию")).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("закрытие лида: в моке он уходит из «клиентов» и несёт номер заявки", async () => {
    const panel = await openLead("L-2044");
    const form = await within(panel).findByRole("form", { name: "Партнёр" });
    fireEvent.change(within(form).getByLabelText("Почта"), {
      target: { value: "partner@demo.example" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Передать как партнёра" }));
    await within(panel).findByText("Лид передан как партнёр");
    const lead = readLeads().leads.find((l) => l.row.lead === "L-2044");
    expect(lead?.card.partner_application).toBeGreaterThan(0);
    expect(lead?.card.client).toBeNull();
  });
});
