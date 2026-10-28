import { HttpResponse, http } from "msw";

import type { About, WhatsNewMark } from "../shared/api/generated/model";
import { buildMe, readSession, updateSession } from "./mockSession";

const expired = () =>
  HttpResponse.json(
    { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
    { status: 401 },
  );

/** «О системе» мока (W-REL): постоянная версия — снимки и e2e не плавают. */
export const MOCK_ABOUT: About = {
  release: { version: "2026.10.28", sha: "1a2b3c4", released_at: "2026-10-28" },
  services: [
    { key: "bff", status: "ok", version: "0.1.0" },
    { key: "crm", status: "ok" },
    { key: "erp", status: "ok" },
    { key: "eds", status: "ok", version: "1a2b3c4" },
  ],
  checked_at: "2026-10-28T09:00:00Z",
};

/** Версия и отметки «Что нового» (W-REL); отметки только растут, как в CRM. */
export const aboutHandlers = [
  http.get("*/about", () => (readSession() ? HttpResponse.json(MOCK_ABOUT) : expired())),

  http.put("*/me/whats-new", async ({ request }) => {
    const session = readSession();
    if (!session) return expired();
    const body = (await request.json()) as WhatsNewMark;
    const grow = (current: string | null | undefined, next: string | undefined) =>
      next && (current ?? "") < next ? next : current;
    const read = grow(session.whatsNewRead, body.read);
    const shown = grow(grow(session.whatsNewShown, body.shown), body.read);
    const next = updateSession({ whatsNewShown: shown ?? null, whatsNewRead: read ?? null });
    const me = next ? buildMe(next) : undefined;
    return me ? HttpResponse.json(me) : expired();
  }),
];
