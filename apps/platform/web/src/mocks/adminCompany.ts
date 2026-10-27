import { HttpResponse, http } from "msw";

import type {
  BrandPreviewIn,
  BrandProfileUpdate,
  CatalogCategoryIn,
  CatalogCategoryUpdate,
  CategoryRequestApproveIn,
  CategoryRequestRejectIn,
  ChargeTemplateIn,
  ChargeTemplateUpdate,
  CompanyProfileUpdate,
  DocumentKind,
  DocumentTemplateCopyIn,
  DocumentTemplateIn,
  DocumentTemplateKind,
  DocumentTemplateUpdate,
  EmailTemplateIn,
  EmailTemplateUpdate,
  FxRateIn,
  NumberingPreviewIn,
  NumberingUpdate,
  PlatformSettingsUpdate,
  QuoteDefaultsUpdate,
  ReferenceItem,
  ReferenceItemIn,
  ReferenceItemUpdate,
  ReferenceKind,
} from "../shared/api/generated/model";
import { isSystemAdmin } from "../entities/role/roles";
import { omit } from "../modules/admin/company/diff";
import { companyDayKey } from "../shared/lib/dates";
import {
  MOCK_LOGO,
  type CompanyMock,
  readCompanyMock,
  updateCompanyMock,
} from "./fixtures/company";
import { buildMe, readSession } from "./mockSession";

type Source = "bff" | "erp";

function fail(
  status: number,
  code: string,
  message: string,
  source: Source = "bff",
  details?: Record<string, unknown>,
) {
  return HttpResponse.json({ code, message, source, ...(details ? { details } : {}) }, { status });
}

const validation = (fields: string[], reason?: string) =>
  fail(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "erp", {
    fields,
    ...(reason ? { reason } : {}),
  });

const conflict = (reason: string, message: string, fields?: string[]) =>
  fail(409, "CONFLICT", message, "erp", { reason, ...(fields ? { fields } : {}) });

const erpForbidden = () =>
  fail(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "erp", {
    backend_status: 403,
  });

interface Caller {
  full: boolean;
  /** Группа `cost_margin` (объединение ролей) */
  margins: boolean;
  /** Администратор платформы в ERP (системная роль «Администратор») */
  platformAdmin: boolean;
  /** Имя сотрудника — в журнале курса */
  name: string;
}

/** Раздел `company.settings` как у BFF: нет сессии — 401, нет раздела — 403, запись — только `full`. */
function guard(need: "read" | "full"): Response | Caller {
  const session = readSession();
  const me = session ? buildMe({ ...session, activeRole: null }) : undefined;
  if (!me) return fail(401, "SESSION_EXPIRED", "Сессия истекла");
  const level = me.resources["company.settings"];
  if (!level || (need === "full" && level !== "full")) {
    return fail(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
      resource: "company.settings",
      need,
    });
  }
  return {
    full: level === "full",
    margins: (me.restricted_fields ?? []).includes("cost_margin"),
    platformAdmin: me.roles.some(isSystemAdmin),
    name: me.name,
  };
}

const isResponse = (value: Response | Caller): value is Response => value instanceof Response;

const nowIso = () => new Date().toISOString();
const nextId = (state: CompanyMock) => String(state.nextId++);

function read(need: "read" | "full", build: (caller: Caller, state: CompanyMock) => unknown) {
  const caller = guard(need);
  if (isResponse(caller)) return caller;
  return HttpResponse.json(build(caller, readCompanyMock()) as never);
}

// Тип тела запроса задаёт вызывающий обработчик (контракт BFF), поэтому параметр один раз в сигнатуре.
// eslint-disable-next-line @typescript-eslint/no-unnecessary-type-parameters
async function write<B>(
  request: Request,
  change: (body: B, state: CompanyMock, caller: Caller) => unknown,
  status = 200,
) {
  const caller = guard("full");
  if (isResponse(caller)) return caller;
  const body = (await request.json().catch(() => ({}))) as B;
  const result = updateCompanyMock((state) => change(body, state, caller));
  return result instanceof Response ? result : HttpResponse.json(result as never, { status });
}

/** Обязательные блоки юридических видов (ERP `REQUIRED_TEMPLATE_BLOCKS`): без них активный шаблон не сохраняется. */
const REQUIRED_BLOCKS: Record<string, { code: string; label: string }[]> = {
  Договор: [
    { code: "doc.spec_table", label: "Блок: спецификация (Приложение № 1)" },
    { code: "doc.totals", label: "Блок: итоги и НДС" },
    { code: "doc.requisites_and_signatures", label: "Блок: реквизиты и подписи Сторон" },
  ],
  Акт: [
    { code: "doc.items_table", label: "Блок: таблица позиций" },
    { code: "doc.totals", label: "Блок: итоги и НДС" },
    { code: "doc.signatures", label: "Блок: подписи сторон" },
  ],
  Счёт: [
    { code: "doc.items_table", label: "Блок: таблица позиций" },
    { code: "doc.totals", label: "Блок: итоги и НДС" },
    { code: "doc.payment_requisites", label: "Блок: платёжные реквизиты" },
  ],
};

/** Вид шаблона словами (ERP `DocumentTemplateKind.name`). */
const TEMPLATE_KIND_NAME: Record<DocumentTemplateKind, string> = {
  letter: "Письмо",
  report: "Рапорт / отчёт",
  custom: "Произвольный",
  contract: "Договор",
  invoice: "Счёт",
  act: "Акт",
  receipt: "Квитанция об оплате",
  delivery_note: "Накладная на отгрузку",
};

/** Отказ ERP `TEMPLATE_MISSING_REQUIRED_BLOCKS` с названиями блоков (C2A-G-5); `null` — состав блоков в порядке. */
function missingBlocksFailure(kindName: string, bodyHtml: string, active: boolean) {
  const required = REQUIRED_BLOCKS[kindName];
  if (!active || !required) return null;
  const present = new Set([...bodyHtml.matchAll(/\{\{\s*([\w.]+)\s*\}\}/g)].map((m) => m[1] ?? ""));
  const missing = required.filter((block) => !present.has(block.code));
  if (missing.length === 0) return null;
  return fail(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "erp", {
    backend_status: 400,
    backend_code: "TEMPLATE_MISSING_REQUIRED_BLOCKS",
    reason: "template_missing_required_blocks",
    missing_blocks: missing,
  });
}

const noContent = () => new HttpResponse(null, { status: 204 });
const notFound = () => fail(404, "NOT_FOUND", "Не найдено.", "erp");

// --- образцы документов и номеров ------------------------------------------------------------

const KIND_WORD: Record<DocumentKind, string> = {
  quote: "Коммерческое предложение",
  contract: "Договор поставки",
  invoice: "Счёт на оплату",
  act: "Акт выполненных работ",
  letter: "Письмо",
};
const KIND_CODE: Record<DocumentKind, string> = {
  quote: "КП",
  contract: "ДОГ",
  invoice: "СЧ",
  act: "АКТ",
  letter: "ПИС",
};
const KINDS = Object.keys(KIND_WORD) as DocumentKind[];

function esc(value: string): string {
  return value.replace(/[&<>"]/g, (c) => `&#${String(c.charCodeAt(0))};`);
}

function sampleHtml(kind: DocumentKind, brand: CompanyMock["brand"]): string {
  const font = brand.font_family === "serif" ? "Georgia, serif" : "Arial, sans-serif";
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>${esc(KIND_WORD[kind])}</title></head>
<body style="font-family:${font};margin:0;padding:24px;color:#1f1f1f">
<div style="border-bottom:3px solid ${esc(brand.accent_color)};padding-bottom:8px;margin-bottom:16px">
<strong style="color:${esc(brand.accent_color)}">${esc(brand.legal_name)}</strong>
<div style="color:${esc(brand.secondary_color)};font-size:12px">ИНН ${esc(brand.inn)}</div></div>
<h2 style="margin:0 0 8px">${esc(KIND_WORD[kind])} № ${esc(KIND_CODE[kind])}-2026-00001</h2>
<p>Образец документа на бланке компании. Позиции, суммы и сроки подставляются при оформлении.</p>
<p style="margin-top:32px">${esc(brand.signatory_position)} ______ ${esc(brand.signatory_name)}</p>
<p style="color:${esc(brand.secondary_color)};font-size:12px">${esc(brand.footer_text)}</p></body></html>`;
}

function renderNumber(
  scheme: Pick<NumberingPreviewIn, "pattern" | "padding" | "start_value" | "prefix">,
  label: string,
): string {
  const now = new Date();
  return scheme.pattern
    .replaceAll("{prefix}", scheme.prefix ? `${scheme.prefix}-` : "")
    .replaceAll("{type}", label)
    .replaceAll("{YYYY}", String(now.getFullYear()))
    .replaceAll("{YY}", String(now.getFullYear()).slice(2))
    .replaceAll("{MM}", String(now.getMonth() + 1).padStart(2, "0"))
    .replaceAll("{seq}", String(scheme.start_value + 1).padStart(scheme.padding, "0"));
}

function applyVariables(text: string): string {
  return text
    .replaceAll("{{number}}", "СЧ-2026-00001")
    .replaceAll("{{amount}}", "12 500 000 сум")
    .replaceAll("{{valid_until}}", "09.11.2026")
    .replaceAll("{{due_date}}", "05.11.2026");
}

const PLACEHOLDER_GROUPS = [
  {
    key: "deal",
    label: "Данные заявки",
    items: [
      { code: "buyer_name", label: "Покупатель" },
      { code: "total", label: "Итоговая сумма" },
      { code: "delivery_term", label: "Срок поставки" },
    ],
  },
  {
    key: "company",
    label: "Реквизиты компании",
    items: [{ code: "seller_name", label: "Наименование продавца" }],
  },
];

const DECIMAL = /^-?\d+(\.\d+)?$/;

/** Ответ `GET /admin/company/fx-rate`: курс и последние 20 записей журнала. */
function fxOverview(state: CompanyMock) {
  const { fx } = state;
  return {
    currency: "USD" as const,
    current: fx.current,
    max_age_days: 7,
    journal: fx.journal.slice(0, 20),
    journal_available: true,
  };
}

/** Без права на группу `cost_margin` поля маржи в ответе отсутствуют (правило 6 CONVENTIONS). */
function quoteFor(caller: Caller, quote: CompanyMock["quote"]) {
  return caller.margins
    ? quote
    : omit(quote, ["default_margin_percent", "min_margin_percent", "target_margin_percent"]);
}

const referenceExtras: Record<ReferenceKind, string[]> = {
  countries: ["alpha2", "alpha3", "iso_numeric", "vat_rate"],
  currencies: ["symbol"],
  units: [],
  "delivery-basis": [
    "description",
    "seller_pays_freight",
    "seller_pays_insurance",
    "seller_pays_import",
    "seller_pays_delivery",
  ],
};
/** Строки, на которые «ссылаются документы»: удалить нельзя, только отключить. */
const IN_USE = new Set(["UZS", "USD", "UZ", "PCS", "FCA"]);

function pickReference(kind: ReferenceKind, body: Record<string, unknown>): Partial<ReferenceItem> {
  const allowed = new Set(["code", "name", "sort_order", "is_active", ...referenceExtras[kind]]);
  return Object.fromEntries(Object.entries(body).filter(([k]) => allowed.has(k)));
}

function foreignFields(kind: ReferenceKind, body: Record<string, unknown>): string[] {
  const allowed = new Set(["code", "name", "sort_order", "is_active", ...referenceExtras[kind]]);
  return Object.keys(body).filter((k) => !allowed.has(k));
}

const isKind = (value: unknown): value is ReferenceKind =>
  value === "countries" ||
  value === "currencies" ||
  value === "units" ||
  value === "delivery-basis";

/** Моки `/admin/company*` (W13-A3, BFF 0.8.0) с правилами ERP: проверки полей, «используется», решения оператора. */
export const adminCompanyHandlers = [
  // --- реквизиты и логотип
  http.get("*/admin/company", () => read("read", (_c, s) => s.company)),
  http.patch("*/admin/company", ({ request }) =>
    write<CompanyProfileUpdate>(request, (body, s) => {
      if (body.name !== undefined && body.name.trim() === "") return validation(["name"]);
      if (body.inn && !/^\d{9}$/.test(body.inn)) return validation(["inn"]);
      if (body.email && !/^[^@\s]+@[^@\s]+$/.test(body.email)) return validation(["email"]);
      s.company = { ...s.company, ...body };
      return s.company;
    }),
  ),
  http.post("*/admin/company/logo", async ({ request }) => {
    const caller = guard("full");
    if (isResponse(caller)) return caller;
    const file = (await request.formData()).get("logo");
    if (!(file instanceof File) || file.size === 0) return validation(["logo"], "file_required");
    if (file.size > 2 * 1024 * 1024) return validation(["logo"], "file_too_large");
    return HttpResponse.json(
      updateCompanyMock((s) => {
        s.company = { ...s.company, logo_url: MOCK_LOGO };
        return s.company;
      }),
    );
  }),
  http.delete("*/admin/company/logo", () => {
    const caller = guard("full");
    if (isResponse(caller)) return caller;
    updateCompanyMock((s) => {
      s.company = { ...s.company, logo_url: null };
    });
    return noContent();
  }),

  // --- бланк и бренд
  http.get("*/admin/company/brand", () => read("read", (_c, s) => s.brand)),
  http.patch("*/admin/company/brand", ({ request }) =>
    write<BrandProfileUpdate>(request, (body, s) => {
      for (const key of ["accent_color", "secondary_color"] as const) {
        const value = body[key];
        if (value && !/^#[0-9a-fA-F]{6}$/.test(value)) {
          return validation([key], `invalid_${key}`);
        }
      }
      s.brand = { ...s.brand, ...body };
      return s.brand;
    }),
  ),
  http.post("*/admin/company/brand/logo", async ({ request }) => {
    const caller = guard("full");
    if (isResponse(caller)) return caller;
    const file = (await request.formData()).get("logo");
    if (!(file instanceof File) || file.size === 0) return validation(["logo"], "file_required");
    return HttpResponse.json(
      updateCompanyMock((s) => {
        s.brand = { ...s.brand, logo_url: MOCK_LOGO };
        return s.brand;
      }),
    );
  }),
  http.post("*/admin/company/brand/preview", async ({ request }) => {
    const caller = guard("read");
    if (isResponse(caller)) return caller;
    const body = (await request.json()) as BrandPreviewIn;
    if (!KINDS.includes(body.kind)) return validation(["kind"]);
    const brand = { ...readCompanyMock().brand, ...(body.draft ?? {}) };
    return HttpResponse.json({ html: sampleHtml(body.kind, brand) });
  }),

  // --- нумерация
  http.get("*/admin/company/numbering", () => read("read", (_c, s) => s.numbering)),
  http.patch("*/admin/company/numbering", ({ request }) =>
    write<NumberingUpdate>(request, (body, s) => {
      if (body.pattern !== undefined && !body.pattern.includes("{seq}")) {
        return validation(["pattern"], "invalid_numbering_pattern");
      }
      if (body.prefix?.toUpperCase() === "TAKEN") {
        return conflict(
          "doc_prefix_taken",
          "Такой префикс нумерации уже занят другой компанией. Выберите другой.",
          ["prefix"],
        );
      }
      const next = {
        ...s.numbering,
        ...body,
        type_labels: { ...s.numbering.type_labels, ...body.type_labels },
      };
      next.is_effective = next.prefix !== "";
      s.numbering = next;
      return s.numbering;
    }),
  ),
  http.post("*/admin/company/numbering/preview", async ({ request }) => {
    const caller = guard("read");
    if (isResponse(caller)) return caller;
    const body = (await request.json()) as NumberingPreviewIn;
    if (!body.pattern.includes("{seq}")) {
      return validation(["pattern"], "invalid_numbering_pattern");
    }
    const labels = { ...readCompanyMock().numbering.type_labels, ...body.type_labels };
    return HttpResponse.json({
      items: KINDS.map((kind) => ({
        kind,
        label: labels[kind] ?? KIND_CODE[kind],
        number: renderNumber(body, labels[kind] ?? KIND_CODE[kind]),
      })),
    });
  }),

  // --- условия КП
  http.get("*/admin/company/quote-defaults", () =>
    read("read", (caller, s) => quoteFor(caller, s.quote)),
  ),
  http.patch("*/admin/company/quote-defaults", ({ request }) =>
    write<QuoteDefaultsUpdate>(request, (body, s, caller) => {
      const margins = ["default_margin_percent", "min_margin_percent", "target_margin_percent"];
      const blocked = Object.keys(body).filter((k) => margins.includes(k));
      if (blocked.length > 0 && !caller.margins) {
        return fail(
          403,
          "FORBIDDEN",
          "Маржу в условиях КП меняют роли с правом видеть себестоимость и маржу.",
          "bff",
          {
            resource: "company.settings",
            restricted: "cost_margin",
            fields: blocked,
          },
        );
      }
      const codes = (kind: ReferenceKind) => s.reference[kind].map((r) => r.code);
      if (body.default_cost_currency && !codes("currencies").includes(body.default_cost_currency)) {
        return validation(["default_cost_currency"], "bad_currency");
      }
      if (
        body.default_delivery_basis &&
        !codes("delivery-basis").includes(body.default_delivery_basis)
      ) {
        return validation(["default_delivery_basis"], "bad_delivery_basis");
      }
      for (const key of [
        "default_vat_rate",
        "default_margin_percent",
        "min_margin_percent",
        "target_margin_percent",
      ] as const) {
        const value = body[key];
        if (value !== undefined && value !== null && !DECIMAL.test(value))
          return validation([key], "bad_number");
      }
      s.quote = { ...s.quote, ...body };
      return quoteFor(caller, s.quote);
    }),
  ),

  // --- статьи расхода
  http.get("*/admin/company/charge-types", () =>
    read("read", (_c, s) => ({ items: s.chargeTypes })),
  ),
  http.get("*/admin/company/charge-templates", () =>
    read("read", (_c, s) => ({ items: s.charges })),
  ),
  http.post("*/admin/company/charge-templates", ({ request }) =>
    write<ChargeTemplateIn>(
      request,
      (body, s) => {
        const basis = s.reference["delivery-basis"].find((b) => b.code === body.delivery_basis);
        const type = s.chargeTypes.find((c) => c.code === body.charge_type);
        if (!basis) return validation(["delivery_basis"]);
        if (!type) return validation(["charge_type"]);
        const created = {
          id: nextId(s),
          delivery_basis: basis.code,
          delivery_basis_name: basis.name,
          charge_type: type.code,
          charge_type_name: type.name,
          default_amount: body.default_amount ?? "0.00",
          default_rate_percent: body.default_rate_percent ?? null,
          is_deduction: body.is_deduction ?? false,
          sort_order: body.sort_order ?? s.charges.length + 1,
          is_active: body.is_active ?? true,
        };
        s.charges.push(created);
        return created;
      },
      201,
    ),
  ),
  http.patch("*/admin/company/charge-templates/:id", ({ request, params }) =>
    write<ChargeTemplateUpdate>(request, (body, s) => {
      const row = s.charges.find((c) => c.id === params["id"]);
      if (!row) return notFound();
      const basis = s.reference["delivery-basis"].find(
        (b) => b.code === (body.delivery_basis ?? row.delivery_basis),
      );
      const type = s.chargeTypes.find((c) => c.code === (body.charge_type ?? row.charge_type));
      if (!basis) return validation(["delivery_basis"]);
      if (!type) return validation(["charge_type"]);
      Object.assign(row, body, {
        delivery_basis: basis.code,
        delivery_basis_name: basis.name,
        charge_type: type.code,
        charge_type_name: type.name,
      });
      return row;
    }),
  ),
  http.delete("*/admin/company/charge-templates/:id", ({ params }) => {
    const caller = guard("full");
    if (isResponse(caller)) return caller;
    return updateCompanyMock((s) => {
      if (!s.charges.some((c) => c.id === params["id"])) return notFound();
      s.charges = s.charges.filter((c) => c.id !== params["id"]);
      return noContent();
    });
  }),

  // --- шаблоны документов
  http.get("*/admin/company/document-templates", () =>
    read("read", (_c, s) => ({ items: s.docTemplates })),
  ),
  http.get("*/admin/company/document-templates/placeholders", () =>
    read("read", () => ({ groups: PLACEHOLDER_GROUPS })),
  ),
  http.post("*/admin/company/document-templates/preview", async ({ request }) => {
    const caller = guard("read");
    if (isResponse(caller)) return caller;
    const body = (await request.json()) as { body_html: string; kind?: DocumentTemplateKind };
    const known = PLACEHOLDER_GROUPS.flatMap((g) => g.items.map((i) => i.code));
    const used = [...body.body_html.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1] ?? "");
    const unknown = used.filter((code) => !known.includes(code));
    const html = body.body_html.replace(/\{\{(\w+)\}\}/g, (_m, code: string) =>
      known.includes(code) ? `[${code}]` : `{{${code}}}`,
    );
    return HttpResponse.json({
      html: `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Образец</title></head><body data-kind="${body.kind ?? "generic"}" style="font-family:Arial,sans-serif;padding:24px">${html}</body></html>`,
      ...(unknown.length > 0 ? { warnings: unknown } : {}),
    });
  }),
  http.post("*/admin/company/document-templates", ({ request }) =>
    write<DocumentTemplateIn>(
      request,
      (body, s) => {
        if (body.name.trim() === "") return validation(["name"]);
        const kind = body.kind ?? "custom";
        const refusal = missingBlocksFailure(
          TEMPLATE_KIND_NAME[kind],
          body.body_html ?? "",
          body.is_active ?? true,
        );
        if (refusal) return refusal;
        const created = {
          id: nextId(s),
          name: body.name,
          kind,
          kind_name: TEMPLATE_KIND_NAME[kind],
          body_html: body.body_html ?? "",
          is_sample: false,
          is_owned: true,
          is_active: body.is_active ?? true,
          placeholders_used: [...(body.body_html ?? "").matchAll(/\{\{(\w+)\}\}/g)].map(
            (m) => m[1] ?? "",
          ),
          updated_at: nowIso(),
        };
        s.docTemplates.push(created);
        return created;
      },
      201,
    ),
  ),
  http.patch("*/admin/company/document-templates/:id", ({ request, params }) =>
    write<DocumentTemplateUpdate>(request, (body, s) => {
      const row = s.docTemplates.find((t) => t.id === params["id"]);
      if (!row) return notFound();
      if (row.is_sample) return erpForbidden();
      if (body.name !== undefined && body.name.trim() === "") return validation(["name"]);
      const refusal = missingBlocksFailure(
        row.kind_name,
        body.body_html ?? row.body_html,
        body.is_active ?? row.is_active,
      );
      if (refusal) return refusal;
      Object.assign(row, body, { updated_at: nowIso() });
      row.placeholders_used = [...row.body_html.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1] ?? "");
      return row;
    }),
  ),
  http.delete("*/admin/company/document-templates/:id", ({ params }) => {
    const caller = guard("full");
    if (isResponse(caller)) return caller;
    return updateCompanyMock((s) => {
      const row = s.docTemplates.find((t) => t.id === params["id"]);
      if (!row) return notFound();
      if (row.is_sample) return erpForbidden();
      // «Договор поставки (наш)» уже использован в оформленных документах.
      if (row.id === "2") {
        return conflict(
          "template_in_use",
          "По шаблону уже оформлены документы. Отключите его вместо удаления.",
        );
      }
      s.docTemplates = s.docTemplates.filter((t) => t.id !== row.id);
      return noContent();
    });
  }),
  http.post("*/admin/company/document-templates/:id/copy", ({ request, params }) =>
    write<DocumentTemplateCopyIn>(request, (body, s) => {
      const source = s.docTemplates.find((t) => t.id === params["id"]);
      if (!source) return notFound();
      if (body.name.trim() === "") return validation(["name"]);
      const copy = {
        ...source,
        id: nextId(s),
        name: body.name,
        is_sample: false,
        is_owned: true,
        updated_at: nowIso(),
      };
      s.docTemplates.push(copy);
      return copy;
    }),
  ),

  // --- шаблоны писем
  http.get("*/admin/company/email-templates", () =>
    read("read", (_c, s) => ({ items: s.emailTemplates })),
  ),
  http.post("*/admin/company/email-templates", ({ request }) =>
    write<EmailTemplateIn>(
      request,
      (body, s) => {
        if (
          s.emailTemplates.some((t) => t.key === body.key && t.language === (body.language ?? "ru"))
        ) {
          return validation(["key"], "unique");
        }
        const created = {
          id: nextId(s),
          key: body.key,
          language: body.language ?? "ru",
          subject: body.subject,
          html_body: body.html_body ?? "",
          text_body: body.text_body,
          available_variables: body.available_variables ?? "",
          is_active: body.is_active ?? true,
          updated_at: nowIso(),
          updated_by: "admin@demo.example",
        };
        s.emailTemplates.push(created);
        return created;
      },
      201,
    ),
  ),
  http.patch("*/admin/company/email-templates/:id", ({ request, params }) =>
    write<EmailTemplateUpdate>(request, (body, s) => {
      const row = s.emailTemplates.find((t) => t.id === params["id"]);
      if (!row) return notFound();
      Object.assign(row, body, { updated_at: nowIso() });
      return row;
    }),
  ),
  http.delete("*/admin/company/email-templates/:id", ({ params }) => {
    const caller = guard("full");
    if (isResponse(caller)) return caller;
    return updateCompanyMock((s) => {
      if (!s.emailTemplates.some((t) => t.id === params["id"])) return notFound();
      s.emailTemplates = s.emailTemplates.filter((t) => t.id !== params["id"]);
      return noContent();
    });
  }),
  http.post("*/admin/company/email-templates/:id/preview", ({ params }) => {
    const caller = guard("read");
    if (isResponse(caller)) return caller;
    const row = readCompanyMock().emailTemplates.find((t) => t.id === params["id"]);
    if (!row) return notFound();
    return HttpResponse.json({
      subject: applyVariables(row.subject),
      text_body: applyVariables(row.text_body),
      html_body: applyVariables(row.html_body),
    });
  }),

  // --- справочники
  http.get("*/admin/company/reference/:kind", ({ params }) => {
    const kind = params["kind"];
    if (!isKind(kind)) return validation(["kind"]);
    return read("read", (_c, s) => ({ items: s.reference[kind] }));
  }),
  http.post("*/admin/company/reference/:kind", ({ request, params }) => {
    const kind = params["kind"];
    if (!isKind(kind)) return validation(["kind"]);
    return write<ReferenceItemIn>(
      request,
      (body, s) => {
        const foreign = foreignFields(kind, body as unknown as Record<string, unknown>);
        if (foreign.length > 0) return validation(foreign, "field_not_in_reference");
        if (s.reference[kind].some((r) => r.code.toLowerCase() === body.code.toLowerCase())) {
          return validation(["code"]);
        }
        const created: ReferenceItem = {
          sort_order: s.reference[kind].length + 1,
          is_active: true,
          ...pickReference(kind, body as unknown as Record<string, unknown>),
          id: nextId(s),
          code: body.code,
          name: body.name,
        };
        s.reference[kind].push(created);
        return created;
      },
      201,
    );
  }),
  http.patch("*/admin/company/reference/:kind/:id", ({ request, params }) => {
    const kind = params["kind"];
    if (!isKind(kind)) return validation(["kind"]);
    return write<ReferenceItemUpdate>(request, (body, s) => {
      const row = s.reference[kind].find((r) => r.id === params["id"]);
      if (!row) return notFound();
      const foreign = foreignFields(kind, body as unknown as Record<string, unknown>);
      if (foreign.length > 0) return validation(foreign, "field_not_in_reference");
      Object.assign(row, pickReference(kind, body as unknown as Record<string, unknown>));
      return row;
    });
  }),
  http.delete("*/admin/company/reference/:kind/:id", ({ params }) => {
    const kind = params["kind"];
    if (!isKind(kind)) return validation(["kind"]);
    const caller = guard("full");
    if (isResponse(caller)) return caller;
    return updateCompanyMock((s) => {
      const row = s.reference[kind].find((r) => r.id === params["id"]);
      if (!row) return notFound();
      if (IN_USE.has(row.code)) {
        return conflict(
          "lookup_in_use",
          "Строка используется в документах и данных. Отключите её вместо удаления.",
        );
      }
      s.reference[kind] = s.reference[kind].filter((r) => r.id !== row.id);
      return noContent();
    });
  }),

  // --- категории и запросы
  http.get("*/admin/company/categories", () => read("read", (_c, s) => ({ items: s.categories }))),
  http.post("*/admin/company/categories", ({ request }) =>
    write<CatalogCategoryIn>(
      request,
      (body, s) => {
        if (body.name.trim() === "") return validation(["name"]);
        if (body.parent_id && !s.categories.some((c) => c.id === body.parent_id))
          return validation(["parent_id"]);
        const created = {
          id: nextId(s),
          name: body.name.trim(),
          parent_id: body.parent_id ?? null,
        };
        s.categories.push(created);
        return created;
      },
      201,
    ),
  ),
  http.patch("*/admin/company/categories/:id", ({ request, params }) =>
    write<CatalogCategoryUpdate>(request, (body, s) => {
      const row = s.categories.find((c) => c.id === params["id"]);
      if (!row) return notFound();
      if (body.name !== undefined && body.name.trim() === "") return validation(["name"]);
      if (body.parent_id === row.id) return validation(["parent_id"]);
      Object.assign(row, body);
      return row;
    }),
  ),
  http.delete("*/admin/company/categories/:id", ({ params }) => {
    const caller = guard("full");
    if (isResponse(caller)) return caller;
    return updateCompanyMock((s) => {
      const row = s.categories.find((c) => c.id === params["id"]);
      if (!row) return notFound();
      if (s.categories.some((c) => c.parent_id === row.id)) {
        return conflict(
          "category_has_children",
          "У категории есть подкатегории. Сначала перенесите или удалите их.",
        );
      }
      s.categories = s.categories.filter((c) => c.id !== row.id);
      return noContent();
    });
  }),
  http.get("*/admin/company/category-requests", ({ request }) => {
    const status = new URL(request.url).searchParams.get("status");
    return read("read", (_c, s) => ({
      items: s.requests.filter((r) => !status || r.status === status),
    }));
  }),
  http.post("*/admin/company/category-requests/:id/approve", ({ request, params }) =>
    write<CategoryRequestApproveIn>(request, (body, s, caller) => {
      if (!caller.platformAdmin) return erpForbidden();
      const row = s.requests.find((r) => r.id === params["id"]);
      if (!row) return notFound();
      const category = s.categories.find((c) => c.id === body.category_id);
      if (!category) return validation(["category_id"], "category_required");
      if (row.status !== "pending")
        return conflict("already_reviewed", "Запрос уже рассмотрен. Обновите список.");
      Object.assign(row, {
        status: "approved",
        resulting_category_id: category.id,
        resulting_category_name: category.name,
        reviewed_at: nowIso(),
      });
      return row;
    }),
  ),
  http.post("*/admin/company/category-requests/:id/reject", ({ request, params }) =>
    write<CategoryRequestRejectIn>(request, (body, s, caller) => {
      if (!caller.platformAdmin) return erpForbidden();
      const row = s.requests.find((r) => r.id === params["id"]);
      if (!row) return notFound();
      if (!body.reason.trim()) return validation(["reason"], "reason_required");
      if (row.status !== "pending")
        return conflict("already_reviewed", "Запрос уже рассмотрен. Обновите список.");
      Object.assign(row, {
        status: "rejected",
        review_notes: body.reason.trim(),
        reviewed_at: nowIso(),
      });
      return row;
    }),
  ),

  // --- платформенные настройки
  http.get("*/admin/company/platform-settings", () => read("read", (_c, s) => s.platform)),
  http.patch("*/admin/company/platform-settings", ({ request }) =>
    write<PlatformSettingsUpdate>(request, (body, s, caller) => {
      if (!caller.platformAdmin) return erpForbidden();
      if (body.vat_rate !== undefined) {
        const value = Number(body.vat_rate);
        if (!DECIMAL.test(body.vat_rate) || value < 0 || value > 100)
          return validation(["vat_rate"], "bad_number");
        s.platform = {
          ...s.platform,
          vat_rate: Number(body.vat_rate).toFixed(2),
          updated_at: nowIso(),
        };
      }
      return s.platform;
    }),
  ),

  // --- курс USD→UZS: ручной ввод и журнал (W13C-F6)
  http.get("*/admin/company/fx-rate", () => read("read", (_c, s) => fxOverview(s))),
  http.post("*/admin/company/fx-rate", ({ request }) =>
    write<FxRateIn>(
      request,
      (body, s, caller) => {
        const today = companyDayKey(new Date()) ?? "";
        if (!/^\d{4}-\d{2}-\d{2}$/.test(body.rate_date))
          return validation(["rate_date"], "fx_rate_date_invalid");
        if (body.rate_date > today) return validation(["rate_date"], "fx_rate_date_in_future");
        if (!/^\d+(\.\d{1,6})?$/.test(body.rate_to_uzs) || Number(body.rate_to_uzs) <= 0)
          return validation(["rate_to_uzs"], "fx_rate_invalid");
        const { fx } = s;
        const rate = String(Number(body.rate_to_uzs));
        const previous = fx.current?.rate_date === body.rate_date ? fx.current : null;
        fx.journal.unshift({
          id: String(s.nextId++),
          kind: "manual",
          rate_date: body.rate_date,
          rate_to_uzs: rate,
          previous_rate_to_uzs: previous?.rate_to_uzs ?? null,
          previous_source: previous?.source ?? null,
          entered_by: caller.name,
          entered_at: nowIso(),
        });
        if (!fx.current || body.rate_date >= fx.current.rate_date)
          fx.current = { rate_to_uzs: rate, rate_date: body.rate_date, source: "manual" };
        s.platform = { ...s.platform, exchange_rate_usd_uzs: rate };
        return fxOverview(s);
      },
      201,
    ),
  ),
];
