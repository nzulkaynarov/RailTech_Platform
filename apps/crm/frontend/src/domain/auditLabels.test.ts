/// <reference types="node" />
/**
 * Тест-сторож (UX волна 3): у каждого действия, которое бэкенд пишет в аудит, есть русское
 * название — журнал не показывает сырые коды (`deal.lost`, `lead.assist`). Коды берутся прямо из
 * `backend/app`: строковые литералы в вызовах `audit.record(...)` и обёрток, которые передают
 * действие дальше (`_finish`, `_replace`). Новое действие без подписи уронит этот тест.
 */
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { t } from "../i18n/ru";
import { auditActionLabel, entityLabel } from "./labels";

// vitest запускается из каталога frontend/ (pnpm test, CI).
const app = resolve(process.cwd(), "../backend/app");
const sources = readdirSync(app, { recursive: true, encoding: "utf8" })
  .filter((name) => name.endsWith(".py"))
  .map((name) => readFileSync(resolve(app, name), "utf8"));
const python = sources.join("\n");
/** Модули, которые пишут аудит: в них f-строка `"x.{…}"` — действие, собранное во время работы. */
const auditing = sources.filter((src) => src.includes("audit.record(")).join("\n");

/** Аргументы вызовов, которые пишут или передают действие аудита (один уровень вложенных скобок). */
const CALLS = /\b(?:record|_finish|_replace)\(((?:[^()]|\([^()]*\))*)\)/g;
const calls = [...python.matchAll(CALLS)].map((m) => m[1] ?? "");
const literal = (args: string) => [...args.matchAll(/(?<!f)"([a-z_]+\.[a-z_]+)"/g)];
const actions = [...new Set(calls.flatMap((args) => literal(args).map((m) => m[1] ?? "")))];
const templates = [
  ...new Set([...auditing.matchAll(/f"([a-z_]+\.[a-z_]*)\{/g)].map((m) => m[1])),
].sort();

/** Действия, которые собираются во время работы: префикс → возможные окончания. */
const RUNTIME: Record<string, string[]> = {
  "deal.": ["open", "won", "lost"],
  "export.": ["leads", "clients", "deals"],
  "lead.close_": ["won", "lost"],
};

/** Типы объектов, которые бэкенд пишет в аудит (`entity_type`, 4-й аргумент `record`). */
const entities = [
  ...new Set(
    [...python.matchAll(/\brecord\(\s*session,\s*[\w.]+,\s*[^,]+,\s*"([a-z_]+)"/g)].map(
      (m) => m[1] ?? "",
    ),
  ),
];

describe("audit labels guard", () => {
  it("parses backend audit calls", () => {
    expect(actions).toEqual(expect.arrayContaining(["lead.take", "lead.assist", "model.update"]));
    expect(entities).toEqual(expect.arrayContaining(["lead", "deal", "system"]));
  });

  it("every literal action code has a Russian name", () => {
    expect(actions.filter((code) => !t.labels.auditAction[code])).toEqual([]);
  });

  it("actions built at runtime are known and labelled", () => {
    expect(templates).toEqual(Object.keys(RUNTIME).sort());
    const built = Object.entries(RUNTIME).flatMap(([prefix, ends]) => ends.map((e) => prefix + e));
    expect(built.filter((code) => !t.labels.auditAction[code])).toEqual([]);
  });

  it("every entity type has a Russian name", () => {
    expect(entities.filter((code) => !t.labels.entity[code])).toEqual([]);
  });

  it("unknown codes fall back to the code itself", () => {
    expect(auditActionLabel("future.action")).toBe("future.action");
    expect(entityLabel("future_entity")).toBe("future_entity");
  });
});
