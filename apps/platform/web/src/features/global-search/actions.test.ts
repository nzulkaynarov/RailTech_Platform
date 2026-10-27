import { describe, expect, it } from "vitest";

import type { Me } from "../../shared/api/generated/model";
import { matchActions } from "./actions";

const me = (resources: Record<string, "read" | "full">): Me =>
  ({ resources, modules: [], roles: [] }) as unknown as Me;
const ADMIN = me({ admin: "full", "crm.clients": "full", "eds.memo.create": "full" });

const keys = (query: string, who: Me = ADMIN) => matchActions(who, query).map((a) => a.key);

describe("действия поиска: совпадение по началу слова от четырёх символов", () => {
  it.each([
    ["заяв", ["createRequest"]],
    ["заявк", ["createRequest"]],
    ["создать заявку", ["createRequest"]],
    ["создать заявку на ремонт", ["createRequest"]],
    ["служе", ["createDocument"]],
    ["служебка", ["createDocument"]],
    ["приглас", ["inviteEmployee"]],
    ["invite", ["inviteEmployee"]],
  ])("«%s»", (query, expected) => {
    expect(keys(query)).toEqual(expected);
  });

  it.each(["за", "зая", "сл", "при", "ВХ-104/26", "L-2041", "демо"])(
    "«%s» — слишком общий или не действие",
    (query) => {
      expect(keys(query)).toEqual([]);
    },
  );

  it("совпадение внутри слова не считается: «явку» — не «заявку»", () => {
    expect(keys("явку")).toEqual([]);
  });

  it("только действия, доступные роли (право записи в разделе)", () => {
    expect(keys("пригласить", me({ "crm.clients": "full" }))).toEqual([]);
    expect(keys("создать заявку", me({ "crm.clients": "read" }))).toEqual([]);
    expect(keys("служебка", me({ "eds.memo.create": "full" }))).toEqual(["createDocument"]);
  });
});
