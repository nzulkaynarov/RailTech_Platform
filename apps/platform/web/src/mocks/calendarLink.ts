import { HttpResponse, http } from "msw";

import { readSession } from "./mockSession";

/** Ссылка на календарь на моках: состояние — в `localStorage` по id сотрудника; секрет — только в ответе выдачи. */
const KEY = "rt-pf-mock-calendar";

function readAll(): Record<string, string> {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

function write(userId: string, issuedAt: string): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...readAll(), [userId]: issuedAt }));
  } catch {
    // без localStorage — только на эту загрузку
  }
}

export const calendarLinkHandlers = [
  http.get("*/me/calendar-link", () => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const issuedAt = readAll()[session.userId] ?? null;
    return HttpResponse.json({ active: issuedAt !== null, issued_at: issuedAt });
  }),
  http.post("*/me/calendar-link", () => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const issuedAt = new Date().toISOString();
    write(session.userId, issuedAt);
    const path = `/api/v1/calendar/demo-calendar-token-${String(Date.now())}-0123456789abcdef.ics`;
    return HttpResponse.json({
      path,
      url: `${window.location.origin}${path}`,
      issued_at: issuedAt,
    });
  }),
];
