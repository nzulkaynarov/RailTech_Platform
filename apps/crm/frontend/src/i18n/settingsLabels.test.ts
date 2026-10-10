/// <reference types="node" />
/**
 * Тест-сторож (дизайн-аудит 2026-10-11, U-07): у каждого поля настроек есть русская подпись,
 * чтобы `SchemaFields` не показывал сырой ключ. Поля берутся прямо из Pydantic-моделей
 * бэкенда — новое поле без подписи уронит этот тест.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { textGroups } from "../domain/settingsLayout";
import { t } from "./ru";

/** Поля Pydantic-классов: строки `    name: type` на уровне класса. */
function modelFields(python: string): Map<string, string[]> {
  const models = new Map<string, string[]>();
  let current: string | null = null;
  for (const line of python.split("\n")) {
    const cls = /^class (\w+)\(/.exec(line);
    if (cls) {
      current = cls[1] ?? null;
      models.set(current ?? "", []);
      continue;
    }
    if (/^\S/.test(line)) current = null;
    const field = /^ {4}(\w+): /.exec(line);
    if (current && field?.[1]) models.get(current)?.push(field[1]);
  }
  return models;
}

// vitest запускается из каталога frontend/ (pnpm test, CI).
const source = readFileSync(resolve(process.cwd(), "../backend/app/schemas/settings.py"), "utf8");
const models = modelFields(source);
const settingsModels = [...models.keys()].filter(
  (name) => name.endsWith("Settings") && name !== "AppSettings",
);

describe("settings labels guard", () => {
  it("parses backend models", () => {
    expect(settingsModels).toContain("TextsSettings");
    expect(models.get("TextsSettings")).toContain("greeting");
  });

  it("every settings section has a Russian name", () => {
    const sections = models.get("AppSettings") ?? [];
    expect(sections.length).toBeGreaterThan(5);
    expect(sections.filter((key) => !t.settings.keys[key])).toEqual([]);
  });

  it("every bot text has a label and «when it is sent»", () => {
    const texts = (models.get("TextsSettings") ?? []).filter((k) => k !== "consent_version");
    expect(texts.length).toBeGreaterThan(20);
    const missing = texts.filter((k) => {
      const text = t.settings.botTexts[k];
      return !text?.label || !text.when;
    });
    expect(missing).toEqual([]);
    expect(textGroups(texts).find((g) => g.key === "other")).toBeUndefined();
  });

  it("every other settings field has a label", () => {
    const fields = settingsModels
      .filter((name) => name !== "TextsSettings")
      .flatMap((name) => models.get(name) ?? []);
    expect(fields.filter((k) => !t.settings.fields[k])).toEqual([]);
    expect(t.settings.fields["consent_version"]).toBeTruthy();
  });
});
