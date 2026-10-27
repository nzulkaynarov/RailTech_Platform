import { HttpResponse, http } from "msw";

import type {
  CalcCatalogPage,
  CalcLine,
  CalcLinePatch,
  CalcLinesIn,
  CalcParseResult,
  CalcRequestList,
  CalcRequestRow,
  CalcSheet,
  CalcVisaState,
  Me,
} from "../shared/api/generated/model";
import { CATALOG, type MockCalc, type MockLine, PARSE_PROPOSAL, seedCalcs } from "./fixtures/calc";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки «Расчёта по заявке» (D2-1, BFF 0.24.0) — поведение BFF и ERP вместе: доступ по разделам каталога (`erp.calc` —
 * чтение и полный, зоны строк — `erp.calc.goods` и `erp.calc.services`), виза строки по зоне, любая правка снимает визу,
 * «Расчёт готов» только со всеми визами (409 `visas_missing`), себестоимость и наценка — только группе `cost_margin`,
 * итоги закупки — и `totals_only`, цены поставщиков — `supplier_prices`. Состояние — в `localStorage` страницы (как сессия
 * мока): сценарий «снабженец → гл. инженер» переживает выход и вход другого сотрудника.
 */
const KEY = "rt-pf-mock-calc-v1";
let memory: MockCalc[] | null = null;

function read(): MockCalc[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as MockCalc[];
  } catch {
    // Хранилище недоступно — состояние в памяти.
  }
  memory ??= seedCalcs();
  return memory;
}

function write(calcs: MockCalc[]): void {
  memory = calcs;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(calcs));
  } catch {
    // Только в памяти.
  }
}

/** Для тестов: исходные данные расчётов. */
export function resetCalcMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // нечего удалять
  }
}

function failure(status: number, code: string, message: string, details?: Record<string, unknown>) {
  const source = details?.["source"] === "erp" ? "erp" : "bff";
  const rest = details
    ? Object.fromEntries(Object.entries(details).filter(([k]) => k !== "source"))
    : {};
  return HttpResponse.json(
    { code, message, source, ...(Object.keys(rest).length ? { details: rest } : {}) },
    { status },
  );
}

const forbidden = (resource: string, need: "read" | "full") =>
  failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", { resource, need });

function me(): Me | null {
  const session = readSession();
  if (!session) return null;
  // Права операций — по объединению ролей, как в BFF.
  return buildMe({ ...session, activeRole: null }) ?? null;
}

function level(user: Me, resource: string): "read" | "full" | undefined {
  return (user.resources as Record<string, "read" | "full" | undefined>)[resource];
}

function fields(user: Me): Set<string> {
  return new Set(user.restricted_fields ?? []);
}

type Guard = { user: Me } | { error: Response };

function guard(resource: string, need: "read" | "full"): Guard {
  const user = me();
  if (!user) return { error: failure(401, "SESSION_EXPIRED", "Сессия истекла") };
  const held = level(user, resource);
  if (!(held === "full" || (need === "read" && held === "read"))) {
    return { error: forbidden(resource, need) };
  }
  return { user };
}

const zoneOf = (line: MockLine): "goods" | "services" =>
  line.kind === "service" ? "services" : "goods";

function canZone(user: Me, zone: "goods" | "services"): boolean {
  return level(user, zone === "goods" ? "erp.calc.goods" : "erp.calc.services") === "full";
}

function lineKind(line: MockLine): CalcLine["kind"] {
  if (line.kind === "service") return "service";
  return line.onHand !== null && line.onHand >= line.quantity && line.onHand > 0
    ? "goods"
    : "goods_to_order";
}

const GROUP = { goods: "stock", goods_to_order: "supply", service: "engineer" } as const;
const money = (value: number) => value.toFixed(2);
const markup = (cost: number, price: number) =>
  cost > 0 ? (((price - cost) / cost) * 100).toFixed(1) : null;
const signed = (line: MockLine) => line.visa !== null && line.visa.zone === zoneOf(line);

function costOf(line: MockLine): number {
  if (line.kind === "service") return (line.crewRate ?? 0) * (line.crewDays ?? 0);
  return line.purchase;
}

function presentLine(line: MockLine, user: Me, editable: boolean): CalcLine {
  const held = fields(user);
  const cost = held.has("cost_margin");
  const kind = lineKind(line);
  const zone = zoneOf(line);
  const unit = costOf(line);
  return {
    id: String(line.id),
    name: line.name,
    article: line.article,
    product_id: line.productId === null ? null : String(line.productId),
    product_name: line.productId === null ? null : line.name,
    kind,
    zone,
    group: GROUP[kind],
    quantity: line.quantity,
    unit: line.unit,
    stock: { on_hand: line.kind === "service" ? null : line.onHand, cell: null, reserved: null },
    supplier: line.supplier
      ? {
          name: line.supplier.name,
          lead_days: line.supplier.leadDays,
          min_order_qty: line.supplier.minOrderQty,
          price_valid_until: line.supplier.validUntil,
          ...(held.has("supplier_prices")
            ? { offer_price: line.supplier.offerPrice, offer_currency: "UZS" }
            : {}),
        }
      : null,
    lead_days: line.leadDays,
    crew_rate: line.crewRate === null ? null : money(line.crewRate),
    crew_days: line.crewDays === null ? null : line.crewDays.toFixed(1),
    client_price: money(line.client),
    ...(cost
      ? {
          purchase_price: zone === "goods" ? money(line.purchase) : null,
          purchase_currency: "UZS",
          cost: money(unit),
          markup_pct: markup(unit, line.client),
        }
      : {}),
    visa: signed(line) && line.visa ? { by: line.visa.by, at: line.visa.at } : null,
    can_edit: editable && canZone(user, zone),
  };
}

function groups(calc: MockCalc) {
  const out = {
    stock: { state: "none" as CalcVisaState, total: 0, signed: 0, by: [] as string[] },
    supply: { state: "none" as CalcVisaState, total: 0, signed: 0, by: [] as string[] },
    engineer: { state: "none" as CalcVisaState, total: 0, signed: 0, by: [] as string[] },
  };
  for (const line of calc.lines) {
    const group = out[GROUP[lineKind(line)]];
    group.total += 1;
    if (signed(line) && line.visa) {
      group.signed += 1;
      if (!group.by.includes(line.visa.by)) group.by.push(line.visa.by);
    }
  }
  for (const group of Object.values(out)) {
    if (group.total) group.state = group.signed === group.total ? "done" : "waiting";
  }
  return out;
}

const editableOf = (calc: MockCalc) =>
  calc.started && (calc.state === "in_progress" || calc.state === "returned");

function present(calc: MockCalc, user: Me): CalcSheet {
  const held = fields(user);
  const cost = held.has("cost_margin");
  const editable = editableOf(calc);
  const lines = calc.lines.map((line) => presentLine(line, user, editable));
  const purchase = calc.lines.reduce((sum, line) => sum + costOf(line) * line.quantity, 0);
  const client = calc.lines.reduce((sum, line) => sum + line.client * line.quantity, 0);
  const missing = lines.filter((line) => line.visa === null).length;
  const blocker = !calc.started
    ? "not_started"
    : !editable
      ? "not_draft"
      : lines.length === 0
        ? "no_lines"
        : missing
          ? "visas_missing"
          : null;
  const path = `/erp/calc/${encodeURIComponent(calc.number)}`;
  return {
    number: calc.number,
    title: calc.title,
    client: calc.client,
    step: calc.stage,
    path,
    task: {
      letter_number: calc.letterNumber,
      letter_subject: calc.letterSubject,
      resolution_text: calc.resolution,
      decided_at: calc.decidedAt,
      decided_by: calc.decidedBy,
      due: calc.due,
      ...(cost ? { min_margin_pct: calc.minMargin } : {}),
      assignees: calc.assignees,
    },
    request: { text: calc.requestText, lines: calc.requestLines },
    quote: calc.started
      ? {
          number: calc.quoteNumber,
          version: 1,
          state: calc.state,
          director_comment: calc.directorComment,
          vat_rate: "12.00",
        }
      : null,
    lines,
    totals: {
      client: money(client),
      ...(cost || held.has("totals_only")
        ? { purchase: money(purchase), markup_pct: markup(purchase, client) }
        : {}),
      vat_included: false,
    },
    visas: groups(calc),
    ready: { allowed: blocker === null, blocker, missing },
    rights: {
      goods: canZone(user, "goods"),
      services: canZone(user, "services"),
      build: level(user, "erp.calc") === "full",
      cost,
    },
  };
}

function row(calc: MockCalc): CalcRequestRow {
  const g = groups(calc);
  return {
    number: calc.number,
    title: calc.title,
    client: calc.client,
    step: calc.stage,
    state: calc.started ? calc.state : "not_started",
    due: calc.due,
    letter_number: calc.letterNumber,
    lines: calc.lines.length,
    visas: { stock: g.stock.state, supply: g.supply.state, engineer: g.engineer.state },
    responsible: calc.manager,
    assignees: calc.assignees,
    path: `/erp/calc/${encodeURIComponent(calc.number)}`,
  };
}

function find(calcs: MockCalc[], number: string): MockCalc | undefined {
  return calcs.find((c) => c.number === decodeURIComponent(number));
}

const notFound = () =>
  failure(404, "NOT_FOUND", "Заявки нет среди заявок с заданием расчёта.", {
    source: "erp",
    reason: "calc_task_not_found",
  });

const conflict = (reason: string, message: string, extra: Record<string, unknown> = {}) =>
  failure(409, "CONFLICT", message, { source: "erp", reason, ...extra });

let nextId = 900;
const jobs = new Map<string, number>();

/** Сотрудник «вида» для «Мои расчёты»: исполнитель зоны по имени из демо-сотрудников. */
function mine(calc: MockCalc, user: Me): boolean {
  return calc.assignees.some((a) => a.name !== null && a.name === user.name);
}

export const erpCalcHandlers = [
  http.get("*/api/v1/erp/calc/requests", ({ request }) => {
    const held = guard("erp.calc", "read");
    if ("error" in held) return held.error;
    const onlyMine = new URL(request.url).searchParams.get("mine") === "true";
    const items = read()
      .filter((calc) => calc.stage === "CALCULATION")
      .filter((calc) => !onlyMine || mine(calc, held.user))
      .sort((a, b) => a.due.localeCompare(b.due))
      .map(row);
    return HttpResponse.json<CalcRequestList>({ items });
  }),

  http.get("*/api/v1/erp/calc/catalog", ({ request }) => {
    const held = guard("erp.calc", "read");
    if ("error" in held) return held.error;
    const words = (new URL(request.url).searchParams.get("q") ?? "")
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    const items = CATALOG.filter((item) =>
      words.every((w) => `${item.name} ${item.article}`.toLowerCase().includes(w)),
    ).map((item) => ({
      id: String(item.id),
      name: item.name,
      article: item.article,
      kind: item.kind,
      on_hand: item.onHand,
      supplier_name: item.supplierName,
      lead_days: item.leadDays,
    }));
    return HttpResponse.json<CalcCatalogPage>({ items: words.length ? items : [] });
  }),

  http.get("*/api/v1/erp/calc-jobs/:job", ({ params }) => {
    const held = guard("erp.calc", "full");
    if ("error" in held) return held.error;
    const job = String(params["job"]);
    const polls = jobs.get(job);
    if (polls === undefined) return failure(404, "NOT_FOUND", "Разбор не найден.");
    jobs.set(job, polls + 1);
    if (polls < 1) return HttpResponse.json<CalcParseResult>({ status: "pending", lines: [] });
    return HttpResponse.json<CalcParseResult>({
      status: "done",
      lines: PARSE_PROPOSAL,
      recognized: PARSE_PROPOSAL.length,
      truncated: false,
    });
  }),

  http.get("*/api/v1/erp/calc/:number", ({ params }) => {
    const held = guard("erp.calc", "read");
    if ("error" in held) return held.error;
    const calc = find(read(), String(params["number"]));
    return calc ? HttpResponse.json<CalcSheet>(present(calc, held.user)) : notFound();
  }),

  http.post("*/api/v1/erp/calc/:number/start", ({ params }) => {
    const held = guard("erp.calc", "full");
    if ("error" in held) return held.error;
    const calcs = read();
    const calc = find(calcs, String(params["number"]));
    if (!calc) return notFound();
    calc.started = true;
    write(calcs);
    return HttpResponse.json<CalcSheet>(present(calc, held.user));
  }),

  http.post("*/api/v1/erp/calc/:number/lines", async ({ params, request }) => {
    const held = guard("erp.calc", "full");
    if ("error" in held) return held.error;
    const body = (await request.json()) as CalcLinesIn;
    const calcs = read();
    const calc = find(calcs, String(params["number"]));
    if (!calc) return notFound();
    for (const item of body.lines) {
      const product = CATALOG.find((p) => String(p.id) === item.product_id);
      const kind = product ? product.kind : item.kind === "service" ? "service" : "goods";
      if (!canZone(held.user, kind === "service" ? "services" : "goods")) {
        return forbidden(kind === "service" ? "erp.calc.services" : "erp.calc.goods", "full");
      }
    }
    calc.started = true;
    for (const item of body.lines) {
      const product = CATALOG.find((p) => String(p.id) === item.product_id);
      const kind = product ? product.kind : item.kind === "service" ? "service" : "goods";
      nextId += 1;
      calc.lines.push({
        id: nextId,
        name: item.name || product?.name || "Позиция",
        article: item.article ?? product?.article ?? "",
        productId: product ? product.id : null,
        kind,
        quantity: item.quantity ?? 1,
        unit: item.unit ?? "",
        onHand: product ? product.onHand : null,
        supplier: null,
        leadDays: product?.leadDays ?? null,
        purchase: product?.purchase ?? 0,
        crewRate: null,
        crewDays: null,
        client: 0,
        visa: null,
      });
    }
    write(calcs);
    return HttpResponse.json<CalcSheet>(present(calc, held.user));
  }),

  http.patch("*/api/v1/erp/calc/:number/lines/:line", async ({ params, request }) => {
    const user = me();
    if (!user) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!canZone(user, "goods") && !canZone(user, "services")) {
      return forbidden("erp.calc.goods", "full");
    }
    const patch = (await request.json()) as CalcLinePatch;
    if (
      (patch.purchase_price !== undefined || patch.purchase_currency !== undefined) &&
      !fields(user).has("cost_margin")
    ) {
      return failure(
        422,
        "VALIDATION_FAILED",
        "Закупку правит сотрудник с доступом к себестоимости.",
        {
          reason: "cost_forbidden",
          fields: ["purchase_price"],
        },
      );
    }
    const calcs = read();
    const calc = find(calcs, String(params["number"]));
    if (!calc) return notFound();
    if (!editableOf(calc)) {
      return conflict("quote_not_draft", "Расчёт уже у директора: строки не правятся.");
    }
    const line = calc.lines.find((l) => String(l.id) === String(params["line"]));
    if (!line) return failure(404, "NOT_FOUND", "Строки нет.", { source: "erp" });
    if (!canZone(user, zoneOf(line))) {
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", {
        source: "erp",
        reason: "zone_not_permitted",
      });
    }
    if (patch.quantity !== undefined) line.quantity = patch.quantity;
    if (patch.purchase_price !== undefined) line.purchase = Number(patch.purchase_price);
    if (patch.crew_rate !== undefined)
      line.crewRate = patch.crew_rate === null ? null : Number(patch.crew_rate);
    if (patch.crew_days !== undefined)
      line.crewDays = patch.crew_days === null ? null : Number(patch.crew_days);
    if (patch.product_id !== undefined && patch.product_id !== null) {
      const product = CATALOG.find((p) => String(p.id) === patch.product_id);
      if (product) {
        line.productId = product.id;
        line.name = product.name;
        line.article = product.article;
        line.onHand = product.onHand;
        line.leadDays = product.leadDays;
        if (!line.purchase) line.purchase = product.purchase;
      }
    }
    if (patch.client_price !== undefined) {
      const price = Number(patch.client_price);
      const cost = costOf(line);
      if (cost <= 0) return conflict("purchase_required", "Сначала укажите закупку.");
      if (price < cost) {
        return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", {
          source: "erp",
          reason: "client_price_below_cost",
          fields: ["client_price"],
        });
      }
      line.client = price;
    }
    line.visa = null;
    write(calcs);
    return HttpResponse.json<CalcSheet>(present(calc, user));
  }),

  http.delete("*/api/v1/erp/calc/:number/lines/:line", ({ params }) => {
    const user = me();
    if (!user) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const calcs = read();
    const calc = find(calcs, String(params["number"]));
    if (!calc) return notFound();
    const line = calc.lines.find((l) => String(l.id) === String(params["line"]));
    if (!line) return failure(404, "NOT_FOUND", "Строки нет.", { source: "erp" });
    if (!canZone(user, zoneOf(line))) return forbidden("erp.calc.goods", "full");
    calc.lines = calc.lines.filter((l) => l !== line);
    write(calcs);
    return HttpResponse.json<CalcSheet>(present(calc, user));
  }),

  http.post("*/api/v1/erp/calc/:number/lines/:line/visa", ({ params }) => {
    const user = me();
    if (!user) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!canZone(user, "goods") && !canZone(user, "services")) {
      return forbidden("erp.calc.goods", "full");
    }
    const calcs = read();
    const calc = find(calcs, String(params["number"]));
    if (!calc) return notFound();
    if (!editableOf(calc)) return conflict("quote_not_draft", "Расчёт уже у директора.");
    const line = calc.lines.find((l) => String(l.id) === String(params["line"]));
    if (!line) return failure(404, "NOT_FOUND", "Строки нет.", { source: "erp" });
    if (!canZone(user, zoneOf(line))) {
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", {
        source: "erp",
        reason: "zone_not_permitted",
      });
    }
    if (costOf(line) <= 0 || line.client <= 0) {
      return conflict("line_incomplete", "Сначала заполните закупку и цену клиенту.");
    }
    line.visa = { by: user.name, at: new Date().toISOString(), zone: zoneOf(line) };
    write(calcs);
    return HttpResponse.json<CalcSheet>(present(calc, user));
  }),

  http.post("*/api/v1/erp/calc/:number/ready", ({ params }) => {
    const held = guard("erp.calc", "full");
    if ("error" in held) return held.error;
    const calcs = read();
    const calc = find(calcs, String(params["number"]));
    if (!calc) return notFound();
    if (!editableOf(calc)) return conflict("quote_not_draft", "Расчёт уже у директора.");
    const missing = calc.lines.filter((line) => !signed(line)).length;
    if (calc.lines.length === 0) return conflict("no_lines", "Добавьте строки.");
    if (missing) {
      return conflict(
        "visas_missing",
        "Не все строки подтверждены: «Расчёт готов» станет доступна после виз всех строк.",
        { missing },
      );
    }
    calc.state = "at_director";
    calc.quoteNumber = "КП-2026/115";
    write(calcs);
    return HttpResponse.json<CalcSheet>(present(calc, held.user));
  }),

  http.post("*/api/v1/erp/calc/:number/parse", ({ params }) => {
    const held = guard("erp.calc", "full");
    if ("error" in held) return held.error;
    if (!find(read(), String(params["number"]))) return notFound();
    nextId += 1;
    const job = `job-${String(nextId)}`;
    jobs.set(job, 0);
    return HttpResponse.json({ job_id: job }, { status: 202 });
  }),
];
