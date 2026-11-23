import { describe, expect, it } from "vitest";

import { LEGACY_REDIRECTS, LEGACY_REMOVE_DATES, legacyPath } from "./legacyRedirects";
import { matchSection } from "./registry";

describe("старые адреса разделов — ЕВ-3б", () => {
  it.each([
    ["/dashboard/projects", "", "/eds/projects"],
    ["/crm/messages", "", "/crm/leads?scope=waiting"],
    ["/crm/messages", "?lead=L-2041", "/crm/leads?scope=waiting&lead=L-2041"],
    ["/crm/requests", "", "/erp/requests"],
    ["/crm/channels", "", "/admin/telegram"],
    ["/eds/outbox", "", "/eds/documents?box=outgoing"],
    [
      "/eds/outbox/%D0%9A%D0%9F-1",
      "?panel=open&tab=card",
      "/eds/drafts/%D0%9A%D0%9F-1?panel=open&tab=card",
    ],
    ["/eds/drafts", "", "/eds/documents?box=outgoing&kind=quote"],
    ["/eds/drafts", "?quote=%D0%9A%D0%9F-1", "/eds/drafts/%D0%9A%D0%9F-1"],
    ["/eds/tasks", "", "/dashboard/queue"],
    ["/eds/approvals", "", "/eds/documents?box=internal"],
    ["/eds/approvals", "?memo=%D0%A1%D0%97-1", "/eds/approvals/%D0%A1%D0%97-1"],
    ["/eds/payments", "?show=bank_changes", "/crm/clients?kind=bank_changes"],
    ["/erp/calc", "", "/erp/requests?mine=1"],
    ["/erp/catalog", "?part=applications", "/crm/clients?kind=applications"],
    ["/erp/catalog", "?part=suppliers", "/crm/clients?kind=partners"],
    ["/chats", "?scope=internal", "/chats"],
    ["/chats", "?scope=external", "/crm/leads?scope=waiting"],
    ["/admin/docflow", "", "/admin/dictionaries?list=doc"],
  ])("%s%s → %s", (path, search, to) => {
    expect(legacyPath(path, search)).toBe(to);
  });

  it.each([
    ["/eds/drafts/1", ""],
    ["/eds/approvals/1", ""],
    ["/eds/tasks/1", ""],
    ["/erp/calc/1", ""],
    ["/eds/payments", "?show=memos"],
    ["/erp/catalog", ""],
    ["/chats", ""],
    ["/eds/mail", ""],
    ["/crm/leads", "?scope=waiting"],
  ])("%s%s — действующий адрес, не трогаем", (path, search) => {
    expect(legacyPath(path, search)).toBeUndefined();
  });

  it("убранные разделы-перенаправления больше не разделы", () => {
    for (const path of [
      "/dashboard/projects",
      "/crm/messages",
      "/crm/requests",
      "/crm/channels",
      "/eds/outbox",
    ]) {
      expect(matchSection(path), path).toBeUndefined();
    }
  });

  it("у каждой строки есть дата удаления, и она ещё не прошла", () => {
    expect(LEGACY_REDIRECTS.length).toBeGreaterThan(0);
    const today = new Date().toISOString().slice(0, 10);
    for (const date of LEGACY_REMOVE_DATES) {
      expect(date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      // Срок вышел — удалите строку вместе с последними ссылками на старый адрес (BFF, письма, справка)
      expect(date >= today, `срок перенаправления ${date} прошёл`).toBe(true);
    }
  });

  it("новый адрес не ведёт обратно на старый (нет цикла)", () => {
    for (const entry of LEGACY_REDIRECTS) {
      for (const query of ["", "?lead=L-1", "?quote=1", "?memo=1", "?scope=internal"]) {
        const to = entry.to(new URLSearchParams(query), "1");
        if (to === undefined) continue;
        const [path = "", search = ""] = to.split("?");
        expect(
          legacyPath(path, search ? `?${search}` : ""),
          `${entry.path}${query}`,
        ).toBeUndefined();
      }
    }
  });
});
