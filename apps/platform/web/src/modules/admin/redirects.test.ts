import { describe, expect, it } from "vitest";

import { matchSection } from "../registry";
import { legacySettingsPath } from "./redirects";

/** Каждый старый адрес Настроек ведёт на действующую страницу (SET-IA): закладки, справка и «Что нового» не ломаются. */
const LEGACY: [string, string][] = [
  ["/admin/bot", "/admin/telegram"],
  ["/admin/bot?part=connection", "/admin/telegram"],
  ["/admin/bot?part=texts", "/admin/telegram?tab=texts"],
  ["/admin/bot?part=behavior", "/admin/telegram?tab=behavior"],
  ["/admin/bot?part=kb", "/admin/telegram?tab=kb"],
  ["/admin/bot?part=templates", "/admin/telegram?tab=templates"],
  ["/admin/bot?part=exports", "/admin/exports"],
  ["/admin/bot?section=company", "/admin/company?part=contacts"],
  ["/admin/bot?part=behavior&section=business_hours", "/admin/timing"],
  ["/admin/bot?section=escalation", "/admin/telegram?tab=behavior"],
  ["/admin/bot?section=stop_words", "/admin/telegram?tab=behavior"],
  ["/admin/bot?section=web_form", "/admin/web-forms"],
  ["/admin/bot?section=notifications", "/admin/notifications"],
  ["/admin/bot?section=service_alerts", "/admin/notifications"],
  ["/admin/bot?section=deals", "/admin/dictionaries?list=deals"],
  ["/admin/bot?section=budget", "/admin/ai-spend"],
  ["/admin/bot?section=texts", "/admin/telegram?tab=texts"],
  ["/admin/bot?section=templates", "/admin/telegram?tab=templates"],
  ["/admin/bot?section=exports", "/admin/exports"],
  [
    "/admin/bot?part=texts&text=greeting&panel=open",
    "/admin/telegram?tab=texts&text=greeting&panel=open",
  ],
  [
    "/admin/bot?section=templates&template=1&panel=open",
    "/admin/telegram?tab=templates&template=1&panel=open",
  ],
  ["/admin/company?tab=details", "/admin/company"],
  ["/admin/company?tab=brand", "/admin/company?part=brand"],
  ["/admin/company?tab=numbering", "/admin/numbering"],
  ["/admin/company?tab=quote", "/admin/sales"],
  ["/admin/templates?tab=quote", "/admin/sales"],
  ["/admin/company?tab=charges", "/admin/dictionaries?list=charges"],
  ["/admin/company?tab=templates", "/admin/templates?tab=documents"],
  ["/admin/company?tab=reference", "/admin/dictionaries?list=countries"],
  ["/admin/company?tab=categories", "/admin/dictionaries?list=categories"],
  ["/admin/company?tab=platform", "/admin/taxes"],
  ["/admin/company?tab=nope", "/admin/company"],
  ["/admin/docflow", "/admin/dictionaries?list=doc"],
  ["/admin/docflow?tab=dictionaries", "/admin/dictionaries?list=doc"],
  ["/admin/docflow?tab=templates", "/admin/templates?tab=resolutions"],
  // ЕВ-2а (2026-11-23): шаблоны резолюций — вкладка «Шаблонов»; ссылка на конкретный шаблон сохраняется
  ["/admin/resolutions", "/admin/templates?tab=resolutions"],
  [
    "/admin/resolutions?template=7&panel=open",
    "/admin/templates?tab=resolutions&template=7&panel=open",
  ],
  ["/admin/docflow?tab=ai", "/admin/ai-spend"],
  ["/admin/tickets", "/dashboard/queue"],
  ["/admin/tickets/", "/dashboard/queue"],
  ["/admin/integrations?card=telegram&panel=open", "/admin/telegram"],
  ["/admin/integrations?card=mail&panel=open", "/admin/mail"],
  ["/admin/integrations?card=spend", "/admin/ai-spend"],
];

describe("старые адреса Настроек → новые (SET-IA)", () => {
  it("виды писем и правила отправителей: из «Справочников» — на страницу «Почта» (ЕВ-2а, 2026-11-23)", () => {
    for (const list of ["mail-types", "doc:mail-types"]) {
      expect(legacySettingsPath("/admin/dictionaries", `list=${list}`)).toBe(
        "/admin/mail#pf-mail-kinds",
      );
    }
    // остальные справочники остаются на месте
    expect(legacySettingsPath("/admin/dictionaries", "list=deals")).toBeNull();
  });

  it.each(LEGACY)("%s → %s", (from, to) => {
    const [pathname = "", search = ""] = from.split("?");
    expect(legacySettingsPath(pathname, search)).toBe(to);
  });

  it.each(LEGACY)("цель %#: действующая страница, а не ещё один редирект", (_from, to) => {
    const [pathname = "", search = ""] = to.split("?");
    expect(legacySettingsPath(pathname, search)).toBeNull();
    expect(matchSection(pathname, search)).toBeDefined();
  });

  it("действующие адреса не трогаются: карточки «Подключений», карточка обращения, страницы групп", () => {
    for (const path of [
      "/admin",
      "/admin/company",
      "/admin/integrations",
      "/admin/tickets/ОБР-0001",
      "/admin/org/7",
      "/admin/telegram",
      "/admin/setup",
    ]) {
      expect(legacySettingsPath(path), path).toBeNull();
    }
    expect(legacySettingsPath("/admin/integrations", "card=erp&panel=open")).toBeNull();
    expect(legacySettingsPath("/admin/company", "part=brand")).toBeNull();
    // вкладка бокового окна (форма банковского счёта) — не старая вкладка страницы
    expect(legacySettingsPath("/admin/company", "panel=open&tab=card")).toBeNull();
  });
});
