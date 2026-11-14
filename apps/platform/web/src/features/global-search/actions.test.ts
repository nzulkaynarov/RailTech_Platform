import { describe, expect, it } from "vitest";

import type { Me } from "../../shared/api/generated/model";
import { matchActions } from "./actions";

const me = (resources: Record<string, "read" | "full">): Me =>
  ({ resources, modules: [], roles: [] }) as unknown as Me;
const ADMIN = me({ admin: "full", "crm.clients": "full", "eds.memo.create": "full" });
const REGISTRAR = me({ "eds.inbox.register": "full" });

const keys = (query: string, who: Me = ADMIN) => matchActions(who, query).map((a) => a.key);

describe("действия поиска: совпадение по началу слова от четырёх символов", () => {
  it.each([
    ["заяв", ["request", "internal"]],
    ["заявк", ["request"]],
    ["создать заявку", ["request"]],
    ["создать заявку на ремонт", ["request"]],
    ["служе", ["internal"]],
    ["служебка", ["internal"]],
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
    expect(keys("служебка", me({ "eds.memo.create": "full" }))).toEqual(["internal"]);
  });
});

describe("виды «Создать» — из реестра окна", () => {
  it("готовый вид находится, неготовый — нет", () => {
    expect(keys("зарегистрировать", REGISTRAR)).toEqual(["incoming"]);
    // План 1.1: «Расчёт» готов — ведёт к выбору заявки; «Сообщение» ждёт чатов
    expect(keys("расчёт", me({ "erp.calc": "full" }))).toEqual(["calc"]);
    expect(keys("сообщение", me({ "chats.internal": "full" }))).toEqual([]);
  });
});
