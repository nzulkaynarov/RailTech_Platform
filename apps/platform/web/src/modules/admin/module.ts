import type { ModuleConfig, SectionConfig } from "../types";
import { SETTINGS, type SettingEntry } from "./settingsRegistry";

/** «Состояние» (ЕВ-2а, отчёт 2026-11-22 §8.3): первый экран Настроек — что требует внимания, службы и готовность. */
export const SETTINGS_HOME = "/admin";

/** Особенности разделов сверх реестра: вкладки бокового окна, карточка объекта. */
const EXTRA: Partial<Record<string, Partial<SectionConfig>>> = {
  roles: { tabs: [{ key: "role" }, { key: "employees" }, { key: "journal" }], defaults: {} },
  org: { detail: "/admin/org/:userId", defaults: {} },
};

function sectionOf(entry: SettingEntry): SectionConfig {
  return {
    key: entry.key,
    path: entry.path,
    access: entry.access,
    group: entry.group,
    tabs: [{ key: "card" }],
    // Настройки занимают всё основное окно: боковое окно закрыто, пока страница сама не откроет его (`?panel=open`).
    defaults: { panelOpen: false },
    actionTo: SETTINGS_HOME,
    ...EXTRA[entry.key],
  };
}

/**
 * Настройки (admin). ЕВ-2а (владелец 2026-11-23, отчёт §8.1): «Состояние» открывается по нажатию на модуль, затем пять групп
 * по одному вопросу — «Люди и доступ», «Компания», «Правила работы», «Каналы и подключения», «Журнал»; не больше двух уровней
 * (группа → страница). Пункты, адреса и права — из реестра `settingsRegistry.ts`. «Первый запуск» — мастер, готовность —
 * часть «Состояния»; «Обращения сотрудников» — в «Моих задачах»; «Обмен между системами» — вид «Истории»
 * (`JournalFilter`). Старые адреса — `redirects.ts`.
 */
export const admin: ModuleConfig = {
  code: "admin",
  sections: [
    {
      key: "overview",
      path: SETTINGS_HOME,
      // Индекс показывает только доступные страницы, поэтому открыт всем, у кого есть хотя бы одна.
      access: { anyOf: ["admin", "company.settings", "eds.signing.manage"] },
      menuAccess: { resource: "admin" },
      tabs: [{ key: "card" }],
      defaults: { panelOpen: false },
      actionTo: "/admin/org",
    },
    ...SETTINGS.map(sectionOf),
    {
      // «Обмен между системами» (шина, W13-A2): вид «Истории» с фильтром, своего пункта меню нет (ЕВ-2а, отчёт §8.2 п. 21).
      key: "bus",
      path: "/admin/bus",
      access: { resource: "admin", level: "full" },
      hidden: true,
      parent: "audit",
      tabs: [{ key: "card" }],
      defaults: { panelOpen: false },
      actionTo: "/admin/audit",
    },
    {
      // «Первый запуск» (W13-A4): мастер; готовность — на «Состоянии», пока шаги не сделаны (ЕВ-2а).
      key: "setup",
      path: "/admin/setup",
      access: { resource: "admin" },
      hidden: true,
      parent: "overview",
      tabs: [{ key: "step" }],
      defaults: { panelOpen: false },
      actionTo: "/admin/org",
    },
    {
      // Карточка обращения (W15-H7): адрес приходит из колокольчика и «Моих задач»; список — в «Моих задачах» (SET-IA).
      key: "tickets",
      path: "/admin/tickets",
      detail: "/admin/tickets/:id",
      access: { resource: "admin" },
      hidden: true,
      parent: "overview",
      tabs: [{ key: "card" }],
      defaults: { panelOpen: false },
      actionTo: "/dashboard/queue",
    },
  ],
};
