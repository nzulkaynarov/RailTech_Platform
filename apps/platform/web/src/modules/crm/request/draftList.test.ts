import { beforeEach, describe, expect, it } from "vitest";

import { copyPath } from "../../erp/calc/api";
import { emptyRequestForm } from "./formModel";
import {
  clearRequestDraft,
  draftContinuePath,
  listRequestDrafts,
  restoreRequestDraft,
  writeRequestDraft,
} from "./draft";

const draftOf = (summary: string) => ({
  state: { ...emptyRequestForm(), summary },
  active: "request" as const,
  contactTouched: false,
  requestKey: crypto.randomUUID(),
});

describe("черновики заявок для вкладки «Черновики» (ЗАЯВ-1)", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("перечисляет черновики своего сотрудника, новее выше, без чужих и без черновиков из входящего", () => {
    const blank = emptyRequestForm();
    writeRequestDraft("u1", "new", blank, false, draftOf("первый"));
    writeRequestDraft("u1", "client:5", blank, false, draftOf("второй"));
    writeRequestDraft("u1", "letter:abc", blank, true, draftOf("из входящего"));
    writeRequestDraft("u2", "new", blank, false, draftOf("чужой"));

    const rows = listRequestDrafts("u1");

    expect(rows.map((row) => row.scope).sort()).toEqual(["client:5", "new"]);
    expect(rows.map((row) => row.draft.state.summary)).not.toContain("чужой");
  });

  it("удалённый черновик возвращается целиком", () => {
    const blank = emptyRequestForm();
    writeRequestDraft("u1", "new", blank, false, draftOf("текст"));
    const [item] = listRequestDrafts("u1");
    if (!item) throw new Error("черновика нет");

    clearRequestDraft("u1", "new");
    expect(listRequestDrafts("u1")).toEqual([]);
    restoreRequestDraft("u1", item.scope, item.draft);

    expect(listRequestDrafts("u1")[0]?.draft.state.summary).toBe("текст");
  });

  it("«Продолжить» ведёт в то место, откуда черновик начат; на телефоне без бокового окна", () => {
    expect(draftContinuePath("new", false)).toBe("/crm/clients?create=1&panel=open&tab=card");
    expect(draftContinuePath("client:5", true)).toBe("/crm/clients?client=5&create=1");
    expect(draftContinuePath("L-0007", false)).toContain("/crm/leads?lead=L-0007&create=1");
  });

  it("«По образцу» открывает форму клиента прежней заявки, а без клиента — просто новую", () => {
    expect(copyPath("ЗВ-2026-081", 3, true)).toBe(
      `/crm/clients?client=3&create=1&template=${encodeURIComponent("ЗВ-2026-081")}`,
    );
    expect(copyPath("ЗВ-2026-081", null, false)).toContain("/crm/clients?create=1&template=");
  });
});
