import type { ModuleCode } from "../../shared/api/generated/model";
import type { SettingsGroup } from "./settingsRegistry";

/**
 * Куда ведёт ⚙ в заголовке подменю модуля (SET-IA; HubSpot — из инструмента сразу в его настройки): «Документы» — Правила
 * работы (справочники писем, шаблоны, сроки), «Клиенты» — Каналы и подключения (бот, почта, формы сайта), «Расчёт» — Правила
 * работы (продажи, справочники). Адрес `/admin?group=` ведёт на первую страницу группы (`StatePage`). У остальных модулей
 * своей группы нет.
 */
export const MODULE_SETTINGS: Readonly<Partial<Record<ModuleCode, SettingsGroup>>> = {
  eds: "rules",
  crm: "channels",
  erp: "rules",
};
