import { HttpResponse, http } from "msw";

import type { BankChangeItem } from "../shared/api/generated/model";
import { readSession } from "./mockSession";

const SEED: BankChangeItem[] = [
  {
    id: "501",
    company_id: "42",
    company_name: "ООО «Северный Путь»",
    company_inn: "305123456",
    company_archived: false,
    status: "pending",
    stale: false,
    old_bank_details: "р/с 20208000123456789001 в АКИБ «Пример»",
    new_bank_details: "р/с 20208000555566667777 в банке «Образец»",
    requested_by_name: "Дильшод Каримов",
    requested_by_email: "admin@north.example",
    requested_ip: "203.0.113.7",
    created_at: "2026-11-08T10:15:00+05:00",
    decided_at: null,
    decided_by_name: null,
    reject_reason: null,
  },
];

let items = SEED.map((item) => ({ ...item }));

export function resetBankChangesMock(): void {
  items = SEED.map((item) => ({ ...item }));
}

function list(url: URL) {
  const status = url.searchParams.get("status");
  return {
    items: status ? items.filter((item) => item.status === status) : items,
    pending_count: items.filter((item) => item.status === "pending").length,
  };
}

export const edsBankChangesHandlers = [
  http.get("*/eds/payments/bank-changes", ({ request }) => {
    if (!readSession()) return new HttpResponse(null, { status: 401 });
    return HttpResponse.json(list(new URL(request.url)));
  }),
  http.post("*/eds/payments/bank-changes/:id/approve", ({ params }) => {
    const item = items.find((row) => row.id === params["id"]);
    if (!item) return new HttpResponse(null, { status: 404 });
    if (item.status === "rejected") {
      return HttpResponse.json(
        {
          code: "CONFLICT",
          message: "Запрос уже решён.",
          details: { reason: "bank_change_not_pending" },
        },
        { status: 409 },
      );
    }
    item.status = "approved";
    item.decided_at = "2026-11-08T11:00:00+05:00";
    item.decided_by_name = "Бухгалтер";
    return HttpResponse.json(item);
  }),
  http.post("*/eds/payments/bank-changes/:id/reject", async ({ params, request }) => {
    const item = items.find((row) => row.id === params["id"]);
    if (!item) return new HttpResponse(null, { status: 404 });
    const body = (await request.json().catch(() => ({}))) as { reason: string };
    item.status = "rejected";
    item.reject_reason = body.reason;
    item.decided_at = "2026-11-08T11:00:00+05:00";
    return HttpResponse.json(item);
  }),
];
