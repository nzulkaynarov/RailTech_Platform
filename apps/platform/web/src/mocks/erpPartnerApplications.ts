import { HttpResponse, http } from "msw";

import type {
  PartnerApplicationCreateRequest,
  PartnerApplicationItem,
} from "../shared/api/generated/model";
import { readSession } from "./mockSession";

/** Договорная часть карточки по умолчанию: договор не подготовлен, кандидат ничего не вернул (ПД-1). */
const NO_CONTRACT = {
  contract_source: "",
  contract_template_id: null,
  contract_template_name: null,
  contract_template_edition: null,
  contract_language: "",
  contract_deviation_text: "",
  contract_approval: "",
  contract_approval_requested_by: null,
  contract_approval_decided_by: null,
  contract_approval_note: "",
  contract_blocker: "CONTRACT_NOT_PREPARED",
  contract_approvers: [],
  can_decide_contract: false,
  decision_needs_confirmation: false,
  candidate_notes: "",
  candidate_returned_at: null,
  has_signed_scan: false,
  signed_scan_at: null,
  contract_votes: [],
  contract_waiting_for: [],
  contract_disagreement: false,
  has_candidate_file: false,
  signed_note: "",
  contract_valid_from: null,
  contract_valid_until: null,
  contract_last_notice_date: null,
  contract_renewal_mode: "",
  package: [],
  from_archive: false,
} as const satisfies Partial<PartnerApplicationItem>;

/** Договор по утверждённому шаблону без отступлений: согласование не нужно, можно отправлять. */
const FROM_TEMPLATE = {
  ...NO_CONTRACT,
  contract_source: "template",
  contract_template_id: "4",
  contract_template_name: "Договор с партнёром",
  contract_template_edition: 2,
  contract_language: "ru",
  contract_blocker: null,
} as const satisfies Partial<PartnerApplicationItem>;

/** Партнёрские шаблоны библиотеки (утверждённые); `[]` в сценарии «нет шаблона» задаёт `rt-pf-mock-no-partner-template`. */
const TEMPLATES = [
  {
    id: "4",
    name: "Договор с партнёром",
    edition: 2,
    languages: ["ru", "en", "uz"],
    is_default: true,
  },
  { id: "5", name: "Агентский договор", edition: 1, languages: ["ru"], is_default: false },
] as const;

function noTemplateScenario(): boolean {
  try {
    return window.localStorage.getItem("rt-pf-mock-no-partner-template") === "1";
  } catch {
    return false;
  }
}

/**
 * Пакет базовых документов (ОСН-1): `rt-pf-mock-package = ready` — у обеих ролей есть утверждённый шаблон,
 * `missing` — у соглашения о неразглашении шаблона нет. Без флага ролей нет: прежний путь «из шаблона».
 */
function packageScenario(): "ready" | "missing" | null {
  try {
    const value = window.localStorage.getItem("rt-pf-mock-package");
    return value === "ready" || value === "missing" ? value : null;
  } catch {
    return null;
  }
}

const PACKAGE_ROLES = [
  {
    base_role: "partnership",
    role_name: "Договор о партнёрстве",
    template_id: "11",
    name: "Договор о партнёрстве",
    edition: 1,
    languages: ["ru", "uz", "en"],
  },
  {
    base_role: "nda",
    role_name: "Соглашение о неразглашении",
    template_id: "12",
    name: "Соглашение о неразглашении",
    edition: 1,
    languages: ["ru"],
  },
] as const;

function packageOptions() {
  const scenario = packageScenario();
  if (!scenario) return { roles: [], ready: false };
  const roles = PACKAGE_ROLES.map((role) =>
    scenario === "missing" && role.base_role === "nda"
      ? { ...role, template_id: null, name: null, edition: null, languages: [] }
      : role,
  );
  return { roles, ready: scenario === "ready" };
}

/** Сценарий «единственный держатель, сам подготовил договор»: решение с подтверждением. */
function soleHolder(): boolean {
  try {
    return window.localStorage.getItem("rt-pf-mock-sole-holder") === "1";
  } catch {
    return false;
  }
}

/** Сценарий «держатель зоны «Право»»: `rt-pf-mock-legal-holder = 1` до входа — сотрудник решает по договорам. */
function legalHolder(): boolean {
  try {
    return window.localStorage.getItem("rt-pf-mock-legal-holder") === "1";
  } catch {
    return false;
  }
}

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
    rejected_reason: "",
    created_at: "2026-11-06T09:30:00+05:00",
    reviewed_at: null,
    matching_company_id: "2",
    matching_company_name: "АО «Южный Металл»",
    company_match_pending: "inn",
    invite_delivery: null,
    ...FROM_TEMPLATE,
    contract_number: "ПД-2026/101",
    contract_date: "2026-11-06",
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
    ...FROM_TEMPLATE,
    contract_blocker: null,
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
    ...FROM_TEMPLATE,
    has_signed_scan: true,
    signed_scan_at: "2026-11-06T09:00:00+05:00",
  },
  {
    id: "104",
    source: "letter",
    source_ref: "ВХ-214/26",
    status: "submitted",
    kind: "supplier",
    company_name: "Nanjing Jichuang Co.",
    inn: "",
    contact_name: "Li Wei",
    email: "li.wei@jichuang.example",
    phone: "",
    language: "en",
    categories_description: "Rail fasteners",
    contract_number: "",
    contract_date: null,
    rejected_reason: "",
    created_at: "2026-11-25T09:00:00+05:00",
    reviewed_at: null,
    matching_company_id: null,
    matching_company_name: null,
    company_match_pending: null,
    invite_delivery: null,
    ...NO_CONTRACT,
  },
  {
    id: "105",
    source: "lead",
    source_ref: "L-318",
    status: "submitted",
    kind: "manufacturer",
    company_name: "Zhengzhou Rail Parts",
    inn: "",
    contact_name: "Chen Hao",
    email: "chen@zrp.example",
    phone: "",
    language: "en",
    categories_description: "Switches and crossings",
    contract_number: "ПД-2026/105",
    contract_date: "2026-11-25",
    rejected_reason: "",
    created_at: "2026-11-24T09:00:00+05:00",
    reviewed_at: null,
    matching_company_id: null,
    matching_company_name: null,
    company_match_pending: null,
    invite_delivery: null,
    ...NO_CONTRACT,
    contract_source: "upload",
    contract_language: "en",
    contract_approval: "requested",
    contract_approval_requested_by: "Мария Снабжение",
    contract_approvers: ["Анвар Юристов"],
    contract_blocker: "CONTRACT_APPROVAL_PENDING",
  },
];

let items: PartnerApplicationItem[] = structuredClone(SEED_APPLICATIONS);

/** Заявка партнёра по id — для «Передать в работу» в моке поручений (план 1.9). */
export function findPartnerApplication(id: string): PartnerApplicationItem | undefined {
  return items.find((i) => i.id === id);
}

export function resetPartnerApplications(): void {
  items = structuredClone(SEED_APPLICATIONS);
}

interface Prepared {
  source: "template" | "upload";
  language: "ru" | "en" | "uz";
  template?: (typeof TEMPLATES)[number];
  deviation: string;
  number?: string | undefined;
  date?: string | undefined;
}

/** Как «Подготовить договор» в ERP: шаблон без отступлений готов к отправке, свой файл и отступление ждут «Право». */
function applyPrepared(item: PartnerApplicationItem, prepared: Prepared): void {
  const needsApproval = prepared.source === "upload" || prepared.deviation.trim() !== "";
  item.contract_source = prepared.source;
  item.contract_template_id = prepared.template?.id ?? null;
  item.contract_template_name = prepared.template?.name ?? null;
  item.contract_template_edition = prepared.template?.edition ?? null;
  item.contract_language = prepared.language;
  item.contract_deviation_text = prepared.deviation.trim();
  item.contract_number = prepared.number || item.contract_number || `ПД-2026/${item.id}`;
  item.contract_date = prepared.date || item.contract_date || "2026-11-25";
  item.contract_approval = needsApproval ? "requested" : "";
  item.contract_approval_requested_by = needsApproval ? "Мария Снабжение" : null;
  item.contract_approval_decided_by = null;
  item.contract_approval_note = "";
  item.contract_approvers = needsApproval ? ["Анвар Юристов"] : [];
  item.contract_blocker = needsApproval ? "CONTRACT_APPROVAL_PENDING" : null;
  item.status = "submitted";
  item.candidate_returned_at = null;
  item.has_signed_scan = false;
  item.signed_scan_at = null;
}

export const erpPartnerApplicationsHandlers = [
  // План 1.9: заявка кандидата по входящему письму — заводит снабжение
  http.post("*/erp/catalog/partner-applications", async ({ request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const body = (await request.json()) as PartnerApplicationCreateRequest;
    const created: PartnerApplicationItem = {
      id: String(200 + items.length),
      source: "letter",
      source_ref: body.source_ref,
      status: "submitted",
      kind: body.kind ?? "supplier",
      company_name: body.company_name,
      inn: body.inn ?? "",
      contact_name: body.contact_name,
      email: body.email.toLowerCase(),
      phone: body.phone ?? "",
      language: body.language ?? "ru",
      categories_description: body.categories_description,
      contract_number: "",
      contract_date: null,
      rejected_reason: "",
      created_at: new Date().toISOString(),
      reviewed_at: null,
      matching_company_id: null,
      matching_company_name: null,
      company_match_pending: null,
      invite_delivery: null,
      ...NO_CONTRACT,
    };
    items = [created, ...items];
    return HttpResponse.json(created, { status: 201 });
  }),
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
      items: filtered.map((i) => ({
        ...i,
        can_decide_contract: legalHolder(),
        decision_needs_confirmation:
          legalHolder() && soleHolder() && i.contract_approval === "requested",
      })),
      pending_count: pendingCount,
    });
  }),

  // ПД-1: из чего готовить договор
  http.get("*/erp/catalog/partner-applications/contract-options", () => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const none = noTemplateScenario();
    return HttpResponse.json({
      templates: none ? [] : TEMPLATES,
      default_template_id: none ? null : "4",
      deviations_allowed: true,
      approvers: ["Анвар Юристов"],
      can_decide: legalHolder(),
      package: packageOptions(),
    });
  }),

  http.post(
    "*/erp/catalog/partner-applications/:id/prepare-contract",
    async ({ params, request }) => {
      const session = readSession();
      if (!session) return new HttpResponse(null, { status: 401 });
      const item = items.find((i) => i.id === params["id"]);
      if (!item) return new HttpResponse(null, { status: 404 });
      const body = (await request.json().catch(() => ({}))) as {
        template_id?: string;
        language?: "ru" | "en" | "uz";
        deviation_text?: string;
        contract_number?: string;
        contract_date?: string;
        package?: boolean;
      };
      if (body.package) {
        if (!packageOptions().ready) {
          return HttpResponse.json(
            {
              code: "VALIDATION_FAILED",
              message: "Проверьте заполнение полей.",
              details: { reason: "no_approved_base_template" },
            },
            { status: 422 },
          );
        }
        applyPrepared(item, {
          source: "template",
          language: body.language ?? "ru",
          template: TEMPLATES[0],
          deviation: "",
          number: body.contract_number,
          date: body.contract_date,
        });
        item.package = PACKAGE_ROLES.map((role, index) => ({
          id: String(900 + index),
          base_role: role.base_role,
          title: role.name,
          number: `${item.contract_number}${index === 0 ? "" : `/${String(index + 1)}`}`,
          template_edition: role.edition,
          has_file: true,
          has_candidate_file: false,
          candidate_remark: "",
          valid_from: null,
          valid_until: null,
          confidentiality_years: role.base_role === "nda" ? 3 : null,
          trade_secret_indefinite: false,
          from_archive: false,
        }));
        return HttpResponse.json(item);
      }
      const template = TEMPLATES.find((t) => t.id === body.template_id);
      if (noTemplateScenario() || !template) {
        return HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "Проверьте заполнение полей.",
            details: { reason: "no_approved_partner_template" },
          },
          { status: 422 },
        );
      }
      applyPrepared(item, {
        source: "template",
        language: body.language ?? "ru",
        template,
        deviation: body.deviation_text ?? "",
        number: body.contract_number,
        date: body.contract_date,
      });
      return HttpResponse.json(item);
    },
  ),

  http.post(
    "*/erp/catalog/partner-applications/:id/prepare-contract-file",
    async ({ params, request }) => {
      const session = readSession();
      if (!session) return new HttpResponse(null, { status: 401 });
      const item = items.find((i) => i.id === params["id"]);
      if (!item) return new HttpResponse(null, { status: 404 });
      const form = await request.formData();
      const field = (name: string): string | undefined => {
        const value = form.get(name);
        return typeof value === "string" && value !== "" ? value : undefined;
      };
      applyPrepared(item, {
        source: "upload",
        language: (field("language") as "ru" | "en" | "uz" | undefined) ?? "ru",
        deviation: field("deviation_text") ?? "",
        number: field("contract_number"),
        date: field("contract_date"),
      });
      return HttpResponse.json(item);
    },
  ),

  // ОСН-1: «Уже подписано на бумаге» — сразу одобрена, реальные даты, без Кабинета
  http.post("*/erp/catalog/partner-applications/:id/from-archive", async ({ params, request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const item = items.find((i) => i.id === params["id"]);
    if (!item) return new HttpResponse(null, { status: 404 });
    const form = await request.formData();
    const field = (name: string): string | undefined => {
      const value = form.get(name);
      return typeof value === "string" && value !== "" ? value : undefined;
    };
    const signedOn = field("signed_on") ?? "";
    item.status = "approved";
    item.from_archive = true;
    item.contract_number = field("contract_number") ?? `ПД-2026/${item.id}`;
    item.contract_date = signedOn;
    item.contract_valid_from = signedOn;
    item.contract_valid_until = `${signedOn.slice(0, 4)}-12-31`;
    item.contract_blocker = null;
    item.package = packageOptions().roles.map((role, index) => ({
      id: String(950 + index),
      base_role: role.base_role,
      title: role.name ?? role.role_name,
      number: `${item.contract_number}${index === 0 ? "" : `/${String(index + 1)}`}`,
      template_edition: role.edition ?? 1,
      has_file: false,
      has_candidate_file: false,
      candidate_remark: "",
      valid_from: field(`signed_on_${role.base_role}`) ?? signedOn,
      valid_until: role.base_role === "nda" ? null : `${signedOn.slice(0, 4)}-12-31`,
      confidentiality_years: role.base_role === "nda" ? 3 : null,
      trade_secret_indefinite: false,
      from_archive: true,
    }));
    return HttpResponse.json(item);
  }),

  http.post(
    "*/erp/catalog/partner-applications/:id/contract-decision",
    async ({ params, request }) => {
      const session = readSession();
      if (!session) return new HttpResponse(null, { status: 401 });
      const item = items.find((i) => i.id === params["id"]);
      if (!item) return new HttpResponse(null, { status: 404 });
      if (!legalHolder()) return new HttpResponse(null, { status: 403 });
      const body = (await request.json()) as { decision: "approve" | "return"; note?: string };
      item.contract_approval = body.decision === "approve" ? "approved" : "returned";
      item.contract_approval_decided_by = "Анвар Юристов";
      item.contract_approval_note = body.note ?? "";
      item.contract_blocker = body.decision === "approve" ? null : "CONTRACT_APPROVAL_RETURNED";
      return HttpResponse.json(item);
    },
  ),

  http.get("*/erp/catalog/partner-applications/:id/document", () => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    return new HttpResponse("%PDF-1.4 mock", {
      headers: {
        "content-type": "application/pdf",
        "content-disposition": 'attachment; filename="contract.pdf"',
      },
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
    if (item.contract_blocker) {
      return HttpResponse.json(
        {
          code: "VALIDATION_FAILED",
          message: "Проверьте заполнение полей.",
          details: { reason: item.contract_blocker.toLowerCase() },
        },
        { status: 422 },
      );
    }
    item.company_match_pending = null;
    item.status = "contract_sent";
    item.candidate_returned_at = null;
    item.invite_delivery = "sent";
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
      signed_note?: string;
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
    if (
      item.contract_source !== "" &&
      !item.has_signed_scan &&
      !body.override_reason &&
      !body.signed_note
    ) {
      return HttpResponse.json(
        {
          code: "VALIDATION_FAILED",
          message: "Проверьте заполнение полей.",
          details: { reason: "signed_proof_required" },
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
