import { HttpResponse, http } from "msw";

import type {
  EscalationSettingsIn,
  KbDocument,
  KbDocumentPatch,
  KbGapResolveIn,
  KbManualDocumentIn,
  KbSearchIn,
  ReplyTemplateIn,
  SandboxMessageIn,
} from "../shared/api/generated/model";
import { failure } from "./adminUsers";
import { type KbMock, MOCK_NOW, SETTINGS_SCHEMAS, readKb, writeKb } from "./fixtures/kb";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки CRM · База знаний и Admin · Настройки бота (W13-A5, BFF 0.11.0). Права — как в BFF: чтение базы знаний — `crm.leads`
 * или `admin`, правка, песочница, настройки, прогон, шаблоны и выгрузки — `admin: full`; шаблоны читает и `crm.leads`
 * полный; выгрузка требует ещё чтение данных (`crm.leads`, `crm.clients`). Ошибки CRM — те же коды и подкоды
 * (`kb_format`, `file_too_large`, `document_indexing`, пути полей настроек), чтобы экран и e2e видели настоящее поведение.
 */
type Level = "read" | "full";
type Rule = readonly [resource: string, need: Level];

function resources(): Record<string, Level> | null {
  const session = readSession();
  if (!session) return null;
  // Права операций — по объединению ролей, а не по активной роли («вид»), как в BFF.
  return buildMe({ ...session, activeRole: null })?.resources ?? null;
}

const rank = (level: Level | undefined) => (level === "full" ? 2 : level === "read" ? 1 : 0);

function guardAny(...rules: Rule[]) {
  const held = resources();
  if (!held) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  if (rules.some(([resource, need]) => rank(held[resource]) >= rank(need))) return null;
  const [resource, need] = rules[0] ?? ["admin", "full"];
  return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
    resource,
    need,
  });
}

const reader = () => guardAny(["crm.leads", "read"], ["admin", "read"]);
const writer = () => guardAny(["admin", "full"]);

function invalid(field: string, reason?: string, extra: Record<string, unknown> = {}) {
  return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "crm", {
    fields: [field],
    ...(reason ? { reason } : {}),
    ...extra,
  });
}

function update(change: (state: KbMock) => void): KbMock {
  const state = readKb();
  change(state);
  writeKb(state);
  return state;
}

const ok = (id: number | null = null) => HttpResponse.json({ id, ok: true });
const MAX_UPLOAD = 25 * 1024 * 1024;

function newDocument(
  state: KbMock,
  body: { title: string; language: KbDocument["language"]; product_key?: string | null },
  source: KbDocument["source_type"],
): KbDocument {
  const created: KbDocument = {
    id: state.nextId++,
    title: body.title,
    product_key: body.product_key ?? null,
    language: body.language,
    source_type: source,
    mime: "text/markdown",
    version: 1,
    is_active: true,
    ingest_status: "pending",
    ingest_error: null,
    chunk_count: 0,
    created_at: MOCK_NOW,
    updated_at: MOCK_NOW,
  };
  state.documents.unshift(created);
  return created;
}

function closeGap(state: KbMock, gapId: number | null | undefined, documentId: number): void {
  const found = state.gaps.find((g) => g.id === gapId);
  if (found) {
    found.status = "resolved";
    found.resolved_document_id = documentId;
  }
}

const FORMAT_FAIL = {
  rule: "front_matter_missing",
  messages: {
    ru: "В начале файла нет front matter: добавьте блок между строками --- с полями title, language, source, updated",
    uz: "Fayl boshida front matter yo‘q: --- qatorlari orasiga title, language, source, updated maydonlarini qo‘shing",
    en: "The file has no front matter: add a block between --- lines with the fields title, language, source, updated",
  },
};

/**
 * Разбор multipart загрузки без `request.formData()`: в jsdom (vitest) разбор форм в Node не знает чужой `File`, а мок
 * работает и там, и в браузере. Файлы в сценариях — текстовые `.md`.
 */
async function parseUpload(
  request: Request,
): Promise<{ fields: Record<string, string>; file: { name: string; size: number } | null }> {
  const boundary = /boundary=([^;]+)/.exec(request.headers.get("content-type") ?? "")?.[1];
  const result: { fields: Record<string, string>; file: { name: string; size: number } | null } = {
    fields: {},
    file: null,
  };
  if (!boundary) return result;
  const text = new TextDecoder().decode(await request.arrayBuffer());
  for (const part of text.split(`--${boundary}`)) {
    const split = part.indexOf("\r\n\r\n");
    if (split < 0) continue;
    const head = part.slice(0, split);
    const body = part.slice(split + 4).replace(/\r\n$/, "");
    const name = /name="([^"]*)"/.exec(head)?.[1];
    const filename = /filename="([^"]*)"/.exec(head)?.[1];
    if (name === undefined) continue;
    if (filename !== undefined) {
      if (name === "file")
        result.file = { name: filename, size: new TextEncoder().encode(body).length };
    } else {
      result.fields[name] = body;
    }
  }
  return result;
}

function unknownProduct(state: KbMock, key: string | null | undefined): boolean {
  return Boolean(key) && !state.products.some((p) => p.key === key);
}

// --- поиск и песочница: простые правила по словам, чтобы сценарии были детерминированы -----------------------------

function searchFor(state: KbMock, body: KbSearchIn) {
  const query = body.query.toLowerCase();
  const pick = (id: number, score: number) => {
    const document = state.documents.find((d) => d.id === id && d.is_active);
    const chunk = state.chunks[String(id)]?.[0];
    return document && chunk
      ? [
          {
            chunk_id: chunk.id,
            document_id: id,
            document_title: document.title,
            heading_path: chunk.heading_path,
            content: chunk.content,
            similarity: score,
            rrf_score: 0.031,
          },
        ]
      : [];
  };
  let hits = [] as ReturnType<typeof pick>;
  if (/срок|постав|доставк/.test(query)) hits = pick(1, 0.83);
  else if (/гаранти/.test(query)) hits = pick(2, 0.78);
  const best = hits[0]?.similarity ?? 0.41;
  return {
    hits,
    best_score: best,
    min_score: 0.7,
    confident: hits.length > 0 && best >= 0.7,
    language: body.language ?? "ru",
  };
}

function sandboxTurn(state: KbMock, body: SandboxMessageIn) {
  const text = body.text.toLowerCase();
  const found = searchFor(state, { query: body.text });
  if (/цен|стоит|сколько/.test(text)) {
    return {
      replies: [
        { text: "Передаю ваш вопрос менеджеру — он ответит в рабочее время.", buttons: [] },
      ],
      why: {
        decision: "handoff",
        reason: "Вопрос о цене — менеджеру",
        best_score: found.best_score,
        documents: [],
        triggers: ["price_or_contract_asked"],
        priority: "hot",
      },
    };
  }
  if (found.confident) {
    return {
      replies: [
        {
          text: "Срок поставки рельсов — от 14 дней со дня оплаты. Уточнить детали?",
          buttons: ["Передать менеджеру", "Не нужно"],
        },
      ],
      why: {
        decision: "answer",
        reason: null,
        best_score: found.best_score,
        documents: found.hits.map((h) => h.document_title),
        triggers: [],
        priority: null,
      },
    };
  }
  return {
    replies: [
      {
        text: "В базе знаний нет ответа на этот вопрос. Передать его менеджеру?",
        buttons: ["Передать менеджеру", "Не нужно"],
      },
    ],
    why: {
      decision: "fallback",
      reason: "Ответ ниже порога",
      best_score: found.best_score,
      documents: [],
      triggers: ["kb_gap_streak"],
      priority: null,
    },
  };
}

// --- настройки ------------------------------------------------------------------------------------------------

const PLACEHOLDER = /\{([a-z_]+)\}/g;

/** Проверка значений раздела так, как это делает модель CRM (достаточно для сценариев): пути невалидных полей. */
function settingPaths(key: string, body: Record<string, unknown>): string[] {
  const paths: string[] = [];
  const name = body["name"];
  if (key === "company" && (typeof name !== "string" || name.trim() === "")) paths.push("name");
  if (key === "texts") {
    for (const [field, value] of Object.entries(body)) {
      // Не все значения раздела — тексты на трёх языках (`consent_version` — строка).
      if (typeof value !== "object" || value === null) continue;
      const localized = value as Record<string, unknown>;
      for (const lang of ["ru", "uz", "en"]) {
        const text = localized[lang];
        if (typeof text !== "string" || text.trim() === "") paths.push(`${field}.${lang}`);
      }
    }
  }
  if (key === "escalation") {
    for (const field of ["sla_minutes", "reminder_minutes", "no_progress_turns", "kb_gap_streak"]) {
      const value = body[field];
      if (typeof value === "number" && value < 1) paths.push(field);
    }
  }
  if (key === "kb") {
    const score = body["min_score"];
    if (typeof score === "number" && (score < 0 || score > 1)) paths.push("min_score");
  }
  return paths.slice(0, 20);
}

function dryRun(body: EscalationSettingsIn) {
  const threshold = body.high_score_threshold ?? 70;
  const disabled = body.disabled_triggers ?? [];
  let candidate = 12;
  if (threshold <= 60) candidate += 3;
  if (threshold >= 80) candidate -= 3;
  if (disabled.includes("complaint")) candidate -= 2;
  candidate = Math.max(candidate, 0);
  const changed =
    candidate === 12
      ? []
      : [
          {
            run_id: 31,
            lead_id: 2041,
            at: MOCK_NOW,
            current: ["complaint"],
            candidate: candidate < 12 ? [] : ["high_score"],
          },
          {
            run_id: 30,
            lead_id: 2038,
            at: MOCK_NOW,
            current: [],
            candidate: candidate > 12 ? ["high_score"] : [],
          },
        ];
  return {
    dialogs: 50,
    escalated_current: 12,
    escalated_candidate: candidate,
    by_code_current: { human_requested: 7, complaint: 3, high_score: 2 },
    by_code_candidate: {
      human_requested: 7,
      complaint: disabled.includes("complaint") ? 1 : 3,
      high_score: candidate - 7 - (disabled.includes("complaint") ? 1 : 3),
    },
    changed,
  };
}

function templateProblem(body: ReplyTemplateIn): string | null {
  if (body.title.trim() === "") return "title";
  if (body.text.ru.trim() === "") return "text";
  for (const lang of ["ru", "uz", "en"] as const) {
    for (const match of body.text[lang].matchAll(PLACEHOLDER)) {
      if (match[1] !== "name" && match[1] !== "manager") return "text";
    }
  }
  return null;
}

// --- выгрузки -------------------------------------------------------------------------------------------------

const EXPORT_DATA: Record<string, string> = {
  leads: "crm.leads",
  clients: "crm.clients",
  deals: "crm.clients",
};
const CSV: Record<string, string> = {
  leads: "ID;Имя;Язык;Стадия\r\n2041;Анна Демо;ru;В диалоге\r\n2038;Бахтиёр Демо;uz;Новый\r\n",
  clients: "ID;Название;Сегмент\r\n17;ООО «Демо-Транс»;Железная дорога\r\n",
  deals: "ID;Название;Сумма;Валюта\r\n88;Поставка рельсов (демо);1500000;UZS\r\n",
};

export const botKbHandlers = [
  // --- документы ---
  http.get("*/crm/kb/documents", ({ request }) => {
    const denied = reader();
    if (denied) return denied;
    const active = new URL(request.url).searchParams.get("active");
    const items = readKb().documents.filter(
      (d) => active === null || String(d.is_active) === active,
    );
    return HttpResponse.json({ items });
  }),

  http.post("*/crm/kb/documents/manual", async ({ request }) => {
    const denied = writer();
    if (denied) return denied;
    const body = (await request.json()) as KbManualDocumentIn;
    if (body.markdown.trim() === "") return invalid("markdown");
    let id = 0;
    const bad = { value: false };
    update((state) => {
      if (unknownProduct(state, body.product_key)) {
        bad.value = true;
        return;
      }
      id = newDocument(state, body, "manual").id;
      closeGap(state, body.gap_id, id);
    });
    return bad.value ? invalid("product_key") : HttpResponse.json({ id }, { status: 201 });
  }),

  http.post("*/crm/kb/documents", async ({ request }) => {
    const denied = writer();
    if (denied) return denied;
    const form = await parseUpload(request);
    const file = form.file;
    const title = (form.fields["title"] ?? "").trim();
    const language = (form.fields["language"] ?? "ru") as KbDocument["language"];
    const product = form.fields["product_key"] ?? null;
    const gap = form.fields["gap_id"] ?? null;
    if (file === null || title === "") return invalid(file === null ? "file" : "title");
    if (!file.name.toLowerCase().endsWith(".md")) return invalid("file", "kb_markdown_only");
    if (file.size === 0) return invalid("file", "file_empty");
    if (file.size > MAX_UPLOAD) return invalid("file", "file_too_large", { max_bytes: MAX_UPLOAD });
    if (file.name.toLowerCase().includes("bad")) return invalid("file", "kb_format", FORMAT_FAIL);
    let id = 0;
    const bad = { value: false };
    update((state) => {
      const productKey = product !== null && product !== "" ? product : null;
      if (unknownProduct(state, productKey)) {
        bad.value = true;
        return;
      }
      id = newDocument(state, { title, language, product_key: productKey }, "file").id;
      closeGap(state, gap === null ? null : Number(gap), id);
    });
    return bad.value ? invalid("product_key") : HttpResponse.json({ id }, { status: 201 });
  }),

  http.get("*/crm/kb/documents/:id", ({ params }) => {
    const denied = reader();
    if (denied) return denied;
    const found = readKb().documents.find((d) => String(d.id) === params["id"]);
    return found ? HttpResponse.json(found) : failure(404, "NOT_FOUND", "Не найдено.", "crm");
  }),

  http.patch("*/crm/kb/documents/:id", async ({ params, request }) => {
    const denied = writer();
    if (denied) return denied;
    const body = (await request.json()) as KbDocumentPatch;
    const missing = { value: false };
    const bad = { value: false };
    update((state) => {
      const found = state.documents.find((d) => String(d.id) === params["id"]);
      if (!found) {
        missing.value = true;
        return;
      }
      if (body.product_key && unknownProduct(state, body.product_key)) {
        bad.value = true;
        return;
      }
      if (body.is_active !== undefined) found.is_active = body.is_active;
      if (body.title !== undefined) found.title = body.title;
      if (body.clear_product) found.product_key = null;
      else if (body.product_key !== undefined) found.product_key = body.product_key;
      found.updated_at = MOCK_NOW;
    });
    if (missing.value) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    return bad.value ? invalid("product_key") : ok();
  }),

  http.get("*/crm/kb/documents/:id/chunks", ({ params }) => {
    const denied = reader();
    if (denied) return denied;
    const state = readKb();
    if (!state.documents.some((d) => String(d.id) === params["id"])) {
      return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    }
    return HttpResponse.json({ items: state.chunks[String(params["id"])] ?? [] });
  }),

  http.post("*/crm/kb/documents/:id/reingest", ({ params }) => {
    const denied = writer();
    if (denied) return denied;
    const outcome = { value: "ok" as "missing" | "busy" | "ok" };
    update((state) => {
      const found = state.documents.find((d) => String(d.id) === params["id"]);
      if (!found) outcome.value = "missing";
      else if (found.ingest_status === "processing") outcome.value = "busy";
      else {
        found.ingest_status = "pending";
        found.ingest_error = null;
      }
    });
    if (outcome.value === "missing") return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    if (outcome.value === "busy") {
      return failure(409, "CONFLICT", "Объект изменился. Обновите страницу.", "crm", {
        reason: "document_indexing",
      });
    }
    return ok();
  }),

  http.post("*/crm/kb/search", async ({ request }) => {
    const denied = reader();
    if (denied) return denied;
    const body = (await request.json()) as KbSearchIn;
    // Нет ключа эмбеддингов (C2A-G-6): CRM отвечает 422 с подкодом, экран подсказывает «Модели ИИ».
    if (body.query.includes("без ключа")) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "crm", {
        backend_status: 422,
        backend_code: "validation_failed",
        reason: "model_key_required",
      });
    }
    return HttpResponse.json(searchFor(readKb(), body));
  }),

  // --- пробелы и продукты ---
  http.get("*/crm/kb/gaps", ({ request }) => {
    const denied = reader();
    if (denied) return denied;
    const query = new URL(request.url).searchParams;
    const status = query.get("status") ?? "open";
    const language = query.get("language");
    const limit = Number(query.get("limit") ?? 50);
    const offset = Number(query.get("offset") ?? 0);
    const all = readKb()
      .gaps.filter((g) => g.status === status && (language === null || g.language === language))
      .sort((a, b) => b.occurrences - a.occurrences || a.id - b.id);
    return HttpResponse.json({ items: all.slice(offset, offset + limit), total: all.length });
  }),

  http.post("*/crm/kb/gaps/:id/resolve", async ({ params, request }) => {
    const denied = writer();
    if (denied) return denied;
    const body = (await request.json()) as KbGapResolveIn;
    const missing = { value: false };
    update((state) => {
      const found = state.gaps.find((g) => String(g.id) === params["id"]);
      if (!found || !state.documents.some((d) => d.id === body.document_id)) missing.value = true;
      else closeGap(state, found.id, body.document_id);
    });
    return missing.value ? failure(404, "NOT_FOUND", "Не найдено.", "crm") : ok();
  }),

  http.post("*/crm/kb/gaps/:id/:action", ({ params }) => {
    const denied = writer();
    if (denied) return denied;
    const action = params["action"];
    if (action !== "ignore" && action !== "reopen") return failure(404, "NOT_FOUND", "Не найдено.");
    const missing = { value: false };
    update((state) => {
      const found = state.gaps.find((g) => String(g.id) === params["id"]);
      if (!found) missing.value = true;
      else {
        found.status = action === "ignore" ? "ignored" : "open";
        found.resolved_document_id = null;
      }
    });
    return missing.value ? failure(404, "NOT_FOUND", "Не найдено.", "crm") : ok();
  }),

  http.get("*/crm/kb/products", () => {
    const denied = reader();
    if (denied) return denied;
    // В CRM справочник продуктов читает только роль с `leads:read`; у администратора без второй роли — 403.
    const held = resources();
    if (rank(held?.["crm.leads"]) < 1) {
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "crm");
    }
    return HttpResponse.json({ items: readKb().products });
  }),

  // --- песочница ---
  http.post("*/crm/sandbox/messages", async ({ request }) => {
    const denied = writer();
    if (denied) return denied;
    const body = (await request.json()) as SandboxMessageIn;
    if (body.text.includes("сбой")) {
      return failure(502, "INTEGRATION_FAILED", "Проверка не прошла.", "crm", {
        reason: "litellm_unavailable",
      });
    }
    const state = update((s) => {
      s.sandboxTurns += 1;
    });
    return HttpResponse.json(sandboxTurn(state, body));
  }),

  http.post("*/crm/sandbox/reset", () => {
    const denied = writer();
    if (denied) return denied;
    update((state) => {
      state.sandboxTurns = 0;
    });
    return new HttpResponse(null, { status: 204 });
  }),

  // --- настройки бота ---
  http.get("*/admin/bot/settings", () => {
    const denied = guardAny(["admin", "read"]);
    if (denied) return denied;
    return HttpResponse.json({ values: readKb().settings, schemas: SETTINGS_SCHEMAS });
  }),

  http.post("*/admin/bot/settings/escalation/dry-run", async ({ request }) => {
    const denied = writer();
    if (denied) return denied;
    return HttpResponse.json(dryRun((await request.json()) as EscalationSettingsIn));
  }),

  http.put("*/admin/bot/settings/:key", async ({ params, request }) => {
    const denied = writer();
    if (denied) return denied;
    const key = String(params["key"]);
    if (!(key in SETTINGS_SCHEMAS)) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    const body = (await request.json()) as Record<string, unknown>;
    const paths = settingPaths(key, body);
    if (paths.length > 0) return invalid(key, undefined, { paths });
    update((state) => {
      state.settings[key] = body;
    });
    return ok();
  }),

  // --- шаблоны ответов ---
  http.get("*/admin/bot/reply-templates", () => {
    const denied = guardAny(["admin", "read"], ["crm.leads", "full"]);
    if (denied) return denied;
    return HttpResponse.json({ items: readKb().templates });
  }),

  http.post("*/admin/bot/reply-templates", async ({ request }) => {
    const denied = writer();
    if (denied) return denied;
    const body = (await request.json()) as ReplyTemplateIn;
    const problem = templateProblem(body);
    if (problem) return invalid(problem);
    let id = 0;
    update((state) => {
      id = state.nextId++;
      state.templates.push({ id, title: body.title.trim(), text: body.text, updated_at: MOCK_NOW });
    });
    return HttpResponse.json({ id }, { status: 201 });
  }),

  http.put("*/admin/bot/reply-templates/:id", async ({ params, request }) => {
    const denied = writer();
    if (denied) return denied;
    const body = (await request.json()) as ReplyTemplateIn;
    const problem = templateProblem(body);
    if (problem) return invalid(problem);
    const missing = { value: false };
    update((state) => {
      const found = state.templates.find((tpl) => String(tpl.id) === params["id"]);
      if (!found) missing.value = true;
      else
        Object.assign(found, { title: body.title.trim(), text: body.text, updated_at: MOCK_NOW });
    });
    return missing.value ? failure(404, "NOT_FOUND", "Не найдено.", "crm") : ok();
  }),

  http.delete("*/admin/bot/reply-templates/:id", ({ params }) => {
    const denied = writer();
    if (denied) return denied;
    const missing = { value: false };
    update((state) => {
      const before = state.templates.length;
      state.templates = state.templates.filter((tpl) => String(tpl.id) !== params["id"]);
      missing.value = state.templates.length === before;
    });
    return missing.value ? failure(404, "NOT_FOUND", "Не найдено.", "crm") : ok();
  }),

  // --- выгрузки CSV ---
  http.get("*/admin/bot/exports/:entity", ({ params }) => {
    const entity = String(params["entity"]);
    const denied = writer();
    if (denied) return denied;
    const needed = EXPORT_DATA[entity];
    if (needed === undefined) return failure(404, "NOT_FOUND", "Не найдено.");
    const denyData = guardAny([needed, "read"]);
    if (denyData) return denyData;
    return new HttpResponse(`\uFEFF${CSV[entity] ?? ""}`, {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="${entity}-20261026-1430.csv"`,
      },
    });
  }),
];
