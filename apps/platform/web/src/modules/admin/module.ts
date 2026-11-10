import type { ModuleConfig, SectionConfig } from "../types";
import { SETTINGS, type SettingEntry } from "./settingsRegistry";

/** Индекс Настроек: поиск, чек-лист первого запуска и пять групп карточек (SET-IA, ресёрч «Настройки» §4.1). */
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
 * Настройки (admin). SET-IA (владелец 2026-11-03): индекс `/admin` и пять групп по задаче администратора — «Люди и доступ»,
 * «Компания», «Каналы связи», «Процессы», «Система»; не больше двух уровней (группа → страница). Пункты, адреса и права — из
 * реестра `settingsRegistry.ts`. «Первый запуск» — чек-лист на индексе, а не пункт меню; «Обращения сотрудников» — в «Моих
 * задачах» (карточка обращения по ссылкам из колокольчика открывается по прежнему адресу). Старые адреса — `redirects.ts`.
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
      // «Первый запуск» (W13-A4): мастер; на индексе — чек-лист, пока шаги не завершены (SET-IA).
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
