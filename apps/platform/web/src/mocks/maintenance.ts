import { HttpResponse, http } from "msw";

/**
 * `/maintenance.json` мока (DECISIONS 2026-11-23): в проде его отдаёт Caddy. e2e кладёт тело в `window.__rtMockMaintenance`
 * (`page.addInitScript`); пока там пусто — 404, как без файла на сервере (баннера нет).
 */
export const maintenanceHandlers = [
  http.get("/maintenance.json", () => {
    const body = (window as unknown as { __rtMockMaintenance?: unknown }).__rtMockMaintenance;
    return body === undefined
      ? new HttpResponse(null, { status: 404 })
      : HttpResponse.json(body as Record<string, unknown>, {
          headers: { "Cache-Control": "no-store" },
        });
  }),
];
