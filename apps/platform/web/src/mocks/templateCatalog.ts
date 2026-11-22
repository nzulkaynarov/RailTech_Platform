import { HttpResponse, http } from "msw";

import type {
  DocumentTemplate,
  EmailTemplate,
  EdsTemplate,
  ReplyTemplate,
  ResolutionTemplate,
  TemplateRow,
} from "../shared/api/generated/model";
import { readSession } from "./mockSession";

/**
 * «Все шаблоны» (план 2.7) на моках: как BFF — список из «доменных» моков тех же разделов от имени сотрудника.
 * Раздел, которого у роли нет (403), просто не попадает в список.
 */
const LANGS = ["ru", "uz", "en"] as const;

async function items<T>(base: string, path: string): Promise<T[] | null> {
  const response = await fetch(new URL(path, base), { credentials: "include" });
  if (!response.ok) return null;
  return ((await response.json()) as { items: T[] }).items;
}

function langs(values: Iterable<string>): TemplateRow["languages"] {
  const present = new Set(values);
  return LANGS.filter((lang) => present.has(lang));
}

export const templateCatalogHandlers = [
  http.get("*/api/v1/templates", async ({ request }) => {
    if (!readSession()) {
      return HttpResponse.json(
        { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
        { status: 401 },
      );
    }
    const base = request.url;
    const [docs, emails, resolutions, replies, letters] = await Promise.all([
      items<DocumentTemplate>(base, "/api/v1/admin/company/document-templates"),
      items<EmailTemplate>(base, "/api/v1/admin/company/email-templates"),
      items<ResolutionTemplate>(base, "/api/v1/eds/resolution-templates"),
      items<ReplyTemplate>(base, "/api/v1/admin/bot/reply-templates"),
      items<EdsTemplate>(base, "/api/v1/eds/templates"),
    ]);
    const rows: TemplateRow[] = [];
    if (docs) {
      for (const doc of docs) {
        rows.push({
          id: `erp.document:${doc.id}`,
          kind: doc.kind,
          name: doc.name,
          domain: "erp",
          languages: ["ru"],
          origin: doc.is_sample ? "builtin" : "custom",
          active: doc.is_active,
          updated_at: doc.updated_at,
          path: `/admin/templates?tab=documents&template=${doc.id}`,
        });
      }
    }
    if (emails) {
      const byKey = new Map<string, EmailTemplate[]>();
      for (const email of emails) byKey.set(email.key, [...(byKey.get(email.key) ?? []), email]);
      for (const [key, group] of [...byKey].sort(([a], [b]) => a.localeCompare(b))) {
        const first = group.find((e) => e.language === "ru") ?? group[0];
        if (!first) continue;
        rows.push({
          id: `erp.email:${key}`,
          kind: "email",
          name: first.subject.replace(/\{\{\s*[\w.]+\s*\}\}/g, "…") || key,
          domain: "erp",
          languages: langs(group.map((e) => e.language)),
          origin: "custom",
          active: group.some((e) => e.is_active),
          path: `/admin/templates?tab=emails&template=${first.id}`,
        });
      }
    }
    for (const item of letters ?? []) {
      rows.push({
        id: `eds.template:${item.id}`,
        kind: item.kind,
        name: item.name,
        domain: "eds",
        languages: item.languages,
        origin: item.origin,
        active: item.active,
        path: `/admin/templates?tab=letters&template=${item.id}`,
      });
    }
    for (const item of resolutions ?? []) {
      rows.push({
        id: `eds.resolution:${item.id}`,
        kind: "resolution",
        name: item.name,
        domain: "eds",
        languages: [],
        origin: "custom",
        active: true,
        path: `/admin/resolutions?template=${item.id}`,
      });
    }
    for (const reply of replies ?? []) {
      rows.push({
        id: `crm.reply:${String(reply.id)}`,
        kind: "reply",
        name: reply.title,
        domain: "crm",
        languages: langs(
          Object.entries(reply.text)
            .filter(([, v]) => typeof v === "string" && v.trim() !== "")
            .map(([k]) => k),
        ),
        origin: "custom",
        active: true,
        path: `/admin/telegram?tab=templates&template=${String(reply.id)}`,
      });
    }
    return HttpResponse.json({ items: rows, sources: { crm: "ok", erp: "ok" } });
  }),
];
