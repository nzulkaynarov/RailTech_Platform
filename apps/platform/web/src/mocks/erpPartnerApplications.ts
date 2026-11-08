import { HttpResponse, http } from "msw";

import type { PartnerApplicationItem } from "../shared/api/generated/model";
import { readSession } from "./mockSession";

const SEED_APPLICATIONS: PartnerApplicationItem[] = [
  {
    id: "101",
    source: "public",
    status: "submitted",
    kind: "manufacturer",
    company_name: "ООО «Сталь-Транс»",
    inn: "7701999888",
    contact_name: "Сергей Кузнецов",
    email: "kuznetsov@stal-trans.example",
    phone: "+998 90 123 45 67",
    language: "ru",
    categories_description: "Стрелочные переводы, рельсовые скрепления, накладки",
    contract_number: "",
    contract_date: null,
    rejected_reason: "",
    created_at: "2026-11-06T09:30:00+05:00",
    reviewed_at: null,
    matching_company_id: "2",
    matching_company_name: "АО «Южный Металл»",
    company_match_pending: "inn",
    invite_delivery: null,
  },
  {
    id: "102",
    source: "client_cabinet",
    status: "contract_sent",
    kind: "supplier",
    company_name: "ООО «Восток Снаб»",
    inn: "7702111222",
    contact_name: "Алишер Умаров",
    email: "umarov@vostok-snab.example",
    phone: "+998 93 987 65 43",
    language: "uz",
    categories_description: "Изоляторы, трансформаторы, кабель силовой",
    contract_number: "ПД-2026/102",
    contract_date: "2026-11-05",
    rejected_reason: "",
    created_at: "2026-11-05T14:15:00+05:00",
    reviewed_at: "2026-11-05T16:00:00+05:00",
    matching_company_id: null,
    matching_company_name: null,
    company_match_pending: null,
    invite_delivery: "failed",
  },
  {
    id: "103",
    source: "public",
    status: "candidate_agreed",
    kind: "principal",
    company_name: "ООО «Рельс Сервис»",
    inn: "7703333444",
    contact_name: "Дилноза Каримова",
    email: "karimova@rels-servis.example",
    phone: "+998 91 555 66 77",
    language: "ru",
    categories_description: "Рельсовые скрепления и подкладки",
    contract_number: "ПД-2026/103",
    contract_date: "2026-11-05",
    rejected_reason: "",
    created_at: "2026-11-04T11:00:00+05:00",
    reviewed_at: "2026-11-05T12:00:00+05:00",
    matching_company_id: null,
    matching_company_name: null,
    company_match_pending: null,
    invite_delivery: "sent",
  },
];

let items: PartnerApplicationItem[] = structuredClone(SEED_APPLICATIONS);

export function resetPartnerApplications(): void {
  items = structuredClone(SEED_APPLICATIONS);
}

export const erpPartnerApplicationsHandlers = [
  http.get("*/erp/catalog/partner-applications", ({ request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const url = new URL(request.url);
    const statusFilter = url.searchParams.get("status");
    const filtered = statusFilter ? items.filter((i) => i.status === statusFilter) : items;
    const pendingCount = items.filter(
      (i) => i.status === "submitted" || i.status === "candidate_agreed",
    ).length;
    return HttpResponse.json({
      items: filtered,
      pending_count: pendingCount,
    });
  }),

  http.post("*/erp/catalog/partner-applications/:id/send-contract", async ({ params, request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const id = params["id"] as string;
    const item = items.find((i) => i.id === id);
    if (!item) return new HttpResponse(null, { status: 404 });
    const body = (await request.json().catch(() => ({}))) as {
      contract_number?: string;
      contract_date?: string | null;
      company_id?: string;
      create_new_company?: boolean;
    };
    if (item.company_match_pending && !body.company_id && !body.create_new_company) {
      return HttpResponse.json(
        {
          code: "VALIDATION_FAILED",
          message: "Проверьте заполнение полей.",
          details: { reason: "company_match_confirmation_required" },
        },
        { status: 422 },
      );
    }
    item.company_match_pending = null;
    item.status = "contract_sent";
    if (body.contract_number) item.contract_number = body.contract_number;
    if (body.contract_date) item.contract_date = body.contract_date;
    item.reviewed_at = "2026-11-06T10:00:00+05:00";
    return HttpResponse.json(item);
  }),

  http.post("*/erp/catalog/partner-applications/:id/approve", async ({ params, request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const id = params["id"] as string;
    const item = items.find((i) => i.id === id);
    if (!item) return new HttpResponse(null, { status: 404 });
    const body = (await request.json().catch(() => ({}))) as {
      contract_number: string;
      contract_date?: string | null;
      kind?: PartnerApplicationItem["kind"];
      company_id?: string;
      create_new_company?: boolean;
      override_reason?: string;
    };
    if (
      item.status !== "candidate_agreed" &&
      !(item.status === "contract_sent" && body.override_reason)
    ) {
      return HttpResponse.json(
        {
          code: "VALIDATION_FAILED",
          message: "Проверьте заполнение полей.",
          details: { reason: "candidate_agreement_required" },
        },
        { status: 422 },
      );
    }
    item.company_match_pending = null;
    item.status = "approved";
    item.contract_number = body.contract_number;
    item.contract_date = body.contract_date ?? "2026-11-06";
    if (body.kind) item.kind = body.kind;
    item.reviewed_at = "2026-11-06T10:00:00+05:00";
    return HttpResponse.json(item);
  }),

  http.post("*/erp/catalog/partner-applications/:id/reject", async ({ params, request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const id = params["id"] as string;
    const item = items.find((i) => i.id === id);
    if (!item) return new HttpResponse(null, { status: 404 });
    const body = (await request.json().catch(() => ({}))) as {
      rejected_reason: string;
    };
    item.status = "rejected";
    item.rejected_reason = body.rejected_reason;
    item.reviewed_at = "2026-11-06T10:00:00+05:00";
    return HttpResponse.json(item);
  }),
];
