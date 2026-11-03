import type { ModuleCode } from "../../shared/api/generated/model";
import type { SettingsGroup } from "./settingsRegistry";

/**
 * Куда ведёт ⚙ в заголовке подменю модуля (SET-IA; HubSpot — из инструмента сразу в его настройки): «Документы» — Процессы
 * (справочники писем, резолюции, шаблоны, сроки), «Клиенты» — Каналы связи (бот, почта, формы сайта), «Расчёт» — Компания
 * (налоги и валюты, нумерация). У остальных модулей своей группы нет.
 */
export const MODULE_SETTINGS: Readonly<Partial<Record<ModuleCode, SettingsGroup>>> = {
  eds: "processes",
  crm: "channels",
  erp: "company",
};
