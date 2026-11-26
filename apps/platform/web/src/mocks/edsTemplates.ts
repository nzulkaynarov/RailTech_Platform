import { HttpResponse, http } from "msw";

import { allows } from "../app/rbac.generated";
import type { EdsTemplate, EdsTemplateIn, EdsTemplatePreview } from "../shared/api/generated/model";
import letterSampleUrl from "./fixtures/letter-sample.pdf?url";
import { buildMe, readSession } from "./mockSession";

/**
 * Шаблоны писем и служебок EDS (TPL-4) на моках: встроенные «Деловое письмо» и «Служебная записка», правка, «Вернуть по
 * умолчанию», предпросмотр сразу готов (демо-PDF письма). Право на правку — делопроизводитель или администратор.
 */
const paragraphs = (lang: "ru" | "uz" | "en", lines: string[]) => ({
  version: 1,
  lang,
  doc: {
    type: "doc",
    content: lines.map((text) => ({ type: "paragraph", content: [{ type: "text", text }] })),
  },
});

const BUILTIN: EdsTemplate[] = [
  {
    id: "5d1d0e1a-0000-4000-8000-000000000001",
    kind: "letter",
    name: "Деловое письмо",
    variants: {
      ru: paragraphs("ru", ["Уважаемые коллеги!", "Сообщаем следующее.", "С уважением,"]),
      uz: paragraphs("uz", [
        "Hurmatli hamkasblar!",
        "Quyidagilarni ma’lum qilamiz.",
        "Hurmat bilan,",
      ]),
      en: paragraphs("en", [
        "Dear colleagues,",
        "We would like to inform you of the following.",
        "Best regards,",
      ]),
    },
    languages: ["ru", "uz", "en"],
    is_default: true,
    active: true,
    origin: "builtin",
    changed: false,
    updated_at: "2026-11-15T09:00:00Z",
  },
  {
    id: "5d1d0e1a-0000-4000-8000-000000000002",
    kind: "memo",
    name: "Служебная записка",
    variants: { ru: paragraphs("ru", ["Прошу рассмотреть следующее.", "Обоснование:"]) },
    languages: ["ru"],
    is_default: true,
    active: true,
    origin: "builtin",
    changed: false,
    updated_at: "2026-11-15T09:00:00Z",
  },
];

let items: EdsTemplate[] = structuredClone(BUILTIN);

export function resetEdsTemplatesMock(): void {
  items = structuredClone(BUILTIN);
}

function held() {
  const session = readSession();
  const me = session ? buildMe(session) : null;
  return me?.resources ?? null;
}

const fail = (status: number, code: string, message: string) =>
  HttpResponse.json({ code, message, source: "eds" }, { status });

function editor(): Response | null {
  const resources = held();
  if (!resources) return fail(401, "SESSION_EXPIRED", "Сессия истекла");
  if (!allows(resources, "eds.inbox.register", "full") && !allows(resources, "admin", "full")) {
    return fail(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
  }
  return null;
}

function apply(row: EdsTemplate, body: EdsTemplateIn): EdsTemplate {
  const languages = (["ru", "uz", "en"] as const).filter((l) => body.variants[l]);
  const builtin = BUILTIN.find((b) => b.id === row.id);
  const next: EdsTemplate = {
    ...row,
    name: body.name,
    variants: body.variants as EdsTemplate["variants"],
    languages,
    active: body.active ?? true,
    changed: builtin ? JSON.stringify(builtin.variants) !== JSON.stringify(body.variants) : false,
    updated_at: new Date().toISOString(),
  };
  if (body.is_default) {
    items = items.map((i) => (i.kind === row.kind ? { ...i, is_default: i.id === row.id } : i));
    next.is_default = true;
  }
  return next;
}

export const edsTemplatesHandlers = [
  http.get("*/eds/templates", ({ request }) => {
    if (!held()) return fail(401, "SESSION_EXPIRED", "Сессия истекла");
    const kind = new URL(request.url).searchParams.get("kind");
    return HttpResponse.json({ items: kind ? items.filter((i) => i.kind === kind) : items });
  }),
  http.post("*/eds/templates", async ({ request }) => {
    const denied = editor();
    if (denied) return denied;
    const body = (await request.json()) as EdsTemplateIn;
    const row: EdsTemplate = apply(
      {
        id: crypto.randomUUID(),
        kind: body.kind,
        name: body.name,
        variants: {},
        languages: [],
        is_default: false,
        active: true,
        origin: "custom",
        changed: false,
        updated_at: new Date().toISOString(),
      },
      body,
    );
    items = [...items, row];
    return HttpResponse.json(row, { status: 201 });
  }),
  http.put("*/eds/templates/:id", async ({ params, request }) => {
    const denied = editor();
    if (denied) return denied;
    const row = items.find((i) => i.id === params["id"]);
    if (!row) return fail(404, "NOT_FOUND", "Шаблон не найден.");
    const next = apply(row, (await request.json()) as EdsTemplateIn);
    items = items.map((i) => (i.id === row.id ? next : i));
    return HttpResponse.json(next);
  }),
  http.post("*/eds/templates/:id/reset", ({ params }) => {
    const denied = editor();
    if (denied) return denied;
    const source = BUILTIN.find((b) => b.id === params["id"]);
    if (!source) return fail(409, "CONFLICT", "Вернуть можно только встроенный шаблон.");
    const current = items.find((i) => i.id === source.id);
    const next = { ...source, is_default: current?.is_default ?? source.is_default };
    items = items.map((i) => (i.id === source.id ? next : i));
    return HttpResponse.json(next);
  }),
  http.post("*/eds/template-previews", () => {
    if (!held()) return fail(401, "SESSION_EXPIRED", "Сессия истекла");
    const preview: EdsTemplatePreview = {
      hash: "b".repeat(64),
      status: "ready",
      error: null,
      pages: 1,
    };
    return HttpResponse.json(preview, { status: 202 });
  }),
  http.get("*/eds/template-previews/:id", () =>
    HttpResponse.json({ hash: "b".repeat(64), status: "ready", error: null, pages: 1 }),
  ),
  http.get("*/eds/template-previews/:id/file", async () => {
    let pdf: ArrayBuffer;
    try {
      pdf = await (await fetch(letterSampleUrl)).arrayBuffer();
    } catch {
      pdf = new TextEncoder().encode("%PDF-1.7\n%%EOF\n").buffer;
    }
    return new HttpResponse(pdf, { headers: { "content-type": "application/pdf" } });
  }),
];
