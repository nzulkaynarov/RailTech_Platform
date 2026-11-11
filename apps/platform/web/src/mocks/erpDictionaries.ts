import { HttpResponse, http } from "msw";

import { allows } from "../app/rbac.generated";
import type {
  Dictionary,
  DictionaryItem,
  DictionaryItemIn,
  DictionaryItemPatch,
  DictionaryOrderIn,
  ReferenceItem,
  ReferenceKind,
} from "../shared/api/generated/model";
import { readCompanyMock, updateCompanyMock } from "./fixtures/company";
import { buildMe, readSession } from "./mockSession";

/**
 * Справочники «Расчёта» ERP на общем ресурсе `/dictionaries` (решение владельца 2026-11-11). Данные — те же строки
 * мока компании (`reference`), что читают остальные экраны: правка здесь видна везде. Код задаёт человек.
 */
const KINDS: readonly ReferenceKind[] = ["countries", "currencies", "units", "delivery-basis"];
/** Строки, на которые ссылаются данные мока: удалить нельзя (как `IN_USE` у прежнего ресурса). */
const IN_USE = new Set(["UZS", "USD", "UZ", "PCS", "FCA"]);

const names = (ru: string, uz: string, en: string) => ({ ru, uz, en });
/** Валюты ведёт ЦБ (источник, решение 2026-11-11): в моке — последнее обновление сегодня в 09:00. */
const CBU = names("ЦБ", "MB", "CBU");
const cbuSyncedAt = () => {
  const at = new Date();
  at.setHours(9, 0, 0, 0);
  return at.toISOString();
};
const flag = (key: string, ru: string, uz: string, en: string) => ({
  key,
  type: "boolean" as const,
  name: names(ru, uz, en),
  required: false,
});

export const ERP_CATALOG: Dictionary[] = [
  {
    kind: "countries",
    owner: "erp",
    area: "calc",
    codes: "given",
    closed: false,
    name: names("Страны", "Mamlakatlar", "Countries"),
    attrs: [
      {
        key: "alpha3",
        type: "text",
        name: names("Код ISO alpha-3", "ISO alpha-3 kodi", "ISO alpha-3"),
        required: false,
      },
      {
        key: "iso_numeric",
        type: "text",
        name: names("Цифровой код ISO", "ISO raqamli kodi", "ISO numeric"),
        required: false,
      },
      {
        key: "vat_rate",
        type: "decimal",
        name: names("Ставка НДС, %", "QQS stavkasi, %", "VAT rate, %"),
        required: false,
      },
    ],
  },
  {
    kind: "currencies",
    owner: "erp",
    area: "calc",
    codes: "given",
    closed: false,
    name: names("Валюты", "Valyutalar", "Currencies"),
    attrs: [
      { key: "symbol", type: "text", name: names("Символ", "Belgi", "Symbol"), required: false },
      {
        key: "iso_numeric",
        type: "text",
        name: names("Цифровой код ISO", "ISO raqamli kodi", "ISO numeric"),
        required: false,
      },
    ],
    source: { name: CBU, synced_at: null },
  },
  {
    kind: "units",
    owner: "erp",
    area: "calc",
    codes: "given",
    closed: false,
    name: names("Единицы измерения", "O‘lchov birliklari", "Units"),
    attrs: [],
  },
  {
    kind: "delivery-basis",
    owner: "erp",
    area: "calc",
    codes: "given",
    closed: false,
    name: names("Базисы поставки", "Yetkazib berish bazislari", "Delivery terms"),
    attrs: [
      {
        key: "description",
        type: "text",
        name: names("Описание", "Tavsif", "Description"),
        required: false,
      },
      flag("seller_pays_freight", "Фрахт за продавцом", "Fraxt sotuvchida", "Seller pays freight"),
      flag(
        "seller_pays_insurance",
        "Страховка за продавцом",
        "Sug‘urta sotuvchida",
        "Seller pays insurance",
      ),
      flag("seller_pays_import", "Ввоз за продавцом", "Import sotuvchida", "Seller pays import"),
      flag(
        "seller_pays_delivery",
        "Доставка за продавцом",
        "Yetkazish sotuvchida",
        "Seller pays delivery",
      ),
    ],
  },
];

type Row = ReferenceItem & { name_uz?: string; name_en?: string } & Record<string, unknown>;

const isErpKind = (value: unknown): value is ReferenceKind =>
  typeof value === "string" && (KINDS as readonly string[]).includes(value);

function access() {
  const session = readSession();
  const me = session ? buildMe({ ...session, activeRole: null }) : null;
  const r = me?.resources ?? {};
  return {
    signedIn: Boolean(me),
    read: allows(r, "company.settings", "read") || allows(r, "admin", "read"),
    write: allows(r, "company.settings", "full") || allows(r, "admin", "full"),
  };
}

export function canReadErpDictionaries(): boolean {
  return access().read;
}

function failure(status: number, code: string, message: string, details?: Record<string, unknown>) {
  return HttpResponse.json(
    { code, message, source: "erp", ...(details ? { details } : {}) },
    { status },
  );
}

function present(kind: ReferenceKind, row: Row): DictionaryItem {
  const spec = ERP_CATALOG.find((d) => d.kind === kind);
  return {
    code: row.code,
    name: { ru: row.name, uz: row.name_uz ?? "", en: row.name_en ?? "" },
    attrs: Object.fromEntries(
      (spec?.attrs ?? []).map((a): [string, boolean | string] => {
        const value: unknown = row[a.key];
        if (a.type === "boolean") return [a.key, value === true];
        return [a.key, typeof value === "string" || typeof value === "number" ? String(value) : ""];
      }),
    ),
    active: row.is_active,
    position: row.sort_order,
    used: null,
    // UZS — база, её ведут руками; остальные валюты пришли из ЦБ.
    source:
      kind === "currencies" && row.code !== "UZS"
        ? { name: CBU, synced_at: cbuSyncedAt(), missing: false }
        : null,
  };
}

function apply(row: Row, body: DictionaryItemPatch): void {
  if (body.name) {
    row.name = body.name.ru;
    row.name_uz = body.name.uz ?? "";
    row.name_en = body.name.en ?? "";
  }
  for (const [key, value] of Object.entries(body.attrs ?? {})) row[key] = value;
  if (typeof body.active === "boolean") row.is_active = body.active;
}

function guard(kind: unknown, write: boolean): Response | ReferenceKind | undefined {
  if (!isErpKind(kind)) return undefined; // не справочник ERP — дальше обработает общий мок
  const who = access();
  if (!who.signedIn) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  if (!(write ? who.write : who.read)) {
    return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
  }
  return kind;
}

/** Каталог ERP мока: у валют — источник с датой обновления. */
export function erpCatalog(): Dictionary[] {
  return ERP_CATALOG.map((d) =>
    d.source ? { ...d, source: { ...d.source, synced_at: cbuSyncedAt() } } : d,
  );
}

export const erpDictionaryHandlers = [
  http.post("*/dictionaries/:kind/sync", ({ params }) => {
    const kind = guard(params["kind"], true);
    if (kind === undefined || kind instanceof Response) return kind;
    const session = readSession();
    const me = session ? buildMe({ ...session, activeRole: null }) : null;
    if (!allows(me?.resources ?? {}, "admin", "full")) {
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    }
    if (kind !== "currencies")
      return failure(404, "NOT_FOUND", "У этого справочника нет источника.");
    return HttpResponse.json({ queued: true }, { status: 202 });
  }),
  http.get("*/dictionaries/:kind", ({ params, request }) => {
    const kind = guard(params["kind"], false);
    if (kind === undefined || kind instanceof Response) return kind;
    const all = new URL(request.url).searchParams.get("include_hidden") === "true";
    const rows = [...(readCompanyMock().reference[kind] as Row[])].sort(
      (a, b) => a.sort_order - b.sort_order,
    );
    return HttpResponse.json({
      items: rows.filter((r) => all || r.is_active).map((r) => present(kind, r)),
    });
  }),
  http.post("*/dictionaries/:kind", async ({ params, request }) => {
    const kind = guard(params["kind"], true);
    if (kind === undefined || kind instanceof Response) return kind;
    const body = (await request.json()) as DictionaryItemIn;
    const code = (body.code ?? "").trim().toUpperCase();
    if (!code)
      return failure(422, "VALIDATION_FAILED", "Укажите код.", { fields: { code: "required" } });
    return updateCompanyMock((s) => {
      const rows = s.reference[kind] as Row[];
      if (rows.some((r) => r.code === code)) {
        return failure(409, "CONFLICT", "Такой код уже есть.", { reason: "code_taken" });
      }
      const row = {
        id: String(Date.now()),
        code,
        name: body.name.ru,
        sort_order: Math.max(0, ...rows.map((r) => r.sort_order)) + 10,
        is_active: true,
      } as Row;
      apply(row, body);
      rows.push(row);
      return HttpResponse.json(present(kind, row), { status: 201 });
    });
  }),
  http.put("*/dictionaries/:kind/order", async ({ params, request }) => {
    const kind = guard(params["kind"], true);
    if (kind === undefined || kind instanceof Response) return kind;
    const body = (await request.json()) as DictionaryOrderIn;
    return updateCompanyMock((s) => {
      const rows = s.reference[kind] as Row[];
      body.codes.forEach((code, index) => {
        const row = rows.find((r) => r.code === code);
        if (row) row.sort_order = (index + 1) * 10;
      });
      return HttpResponse.json({
        items: [...rows].sort((a, b) => a.sort_order - b.sort_order).map((r) => present(kind, r)),
      });
    });
  }),
  http.patch("*/dictionaries/:kind/:code", async ({ params, request }) => {
    const kind = guard(params["kind"], true);
    if (kind === undefined || kind instanceof Response) return kind;
    const body = (await request.json()) as DictionaryItemPatch;
    return updateCompanyMock((s) => {
      const row = (s.reference[kind] as Row[]).find((r) => r.code === params["code"]);
      if (!row) return failure(404, "NOT_FOUND", "Такого значения в справочнике нет.");
      apply(row, body);
      return HttpResponse.json(present(kind, row));
    });
  }),
  http.delete("*/dictionaries/:kind/:code", ({ params }) => {
    const kind = guard(params["kind"], true);
    if (kind === undefined || kind instanceof Response) return kind;
    return updateCompanyMock((s) => {
      const rows = s.reference[kind] as Row[];
      const row = rows.find((r) => r.code === params["code"]);
      if (!row) return failure(404, "NOT_FOUND", "Такого значения в справочнике нет.");
      if (IN_USE.has(row.code)) {
        return failure(409, "CONFLICT", "Значение уже используется — его можно только скрыть.", {
          reason: "value_in_use",
        });
      }
      s.reference[kind] = rows.filter((r) => r.code !== row.code);
      return new HttpResponse(null, { status: 204 });
    });
  }),
];
