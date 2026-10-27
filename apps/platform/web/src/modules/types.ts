import type { AccessLevel, ModuleCode } from "../shared/api/generated/model";

/**
 * Правило доступа к разделу: ключ ресурса матрицы `platform-rbac.yaml` или «любой из». Уровень берётся из `Me.resources`;
 * `level: "full"` — раздел только для полного доступа (Настройки · Обмен между системами: чтения уровня `read` у него нет).
 */
export type AccessRule = ({ resource: string } | { anyOf: readonly string[] }) & {
  level?: AccessLevel;
};

export interface PanelTab {
  /** Ключ вкладки в `?tab=` и в `modules:tabs.<key>` */
  key: string;
}

export interface SectionConfig {
  /** Ключ раздела: совпадает с `MenuCounter.section` контракта и с `modules:<module>.sections.<key>` */
  key: string;
  /** Путь пункта подменю (SPEC-v3 §6.3); `?tab=` в пути — фильтр списка, как у Chats */
  path: string;
  /** Путь карточки объекта (`/crm/leads/:id`) */
  detail?: string;
  access: AccessRule;
  /** Нет в подменю (экран открывается кнопкой, например «Создать документ») */
  hidden?: boolean;
  /** Вкладки бокового окна; первая — по действию экрана (SPEC-v3 §6.1). По умолчанию — Карточка · Чат проекта · Документы */
  tabs?: readonly PanelTab[];
  /** Состояния панелей по умолчанию (SPEC-v3 приложение А); без поля — обе открыты */
  defaults?: { menuOpen?: boolean; panelOpen?: boolean };
  /** Куда ведёт действие пустого состояния; без поля — кнопка неактивна («появится в фазе P2») */
  actionTo?: string;
}

export interface ModuleAction {
  /** Подпись берётся из `modules:<module>.action` */
  access: string;
  /** Куда ведёт кнопка; без поля — неактивная («появится в фазе P2») */
  to?: string;
}

/**
 * Модуль рейла. Порядок — в `MODULES` (registry.ts). Имена переводятся (UX-оценка 2026-10-27 §6.1):
 * `modules:<code>.name` — подпись в рейле, нижней панели и хлебных крошках (≤ 10 символов),
 * `modules:<code>.title` — заголовок подменю без номера; код модуля (`crm`, `eds`, `erp`) остаётся только в URL и коде.
 */
export interface ModuleConfig {
  code: ModuleCode;
  sections: readonly SectionConfig[];
  /** Главное действие модуля внизу подменю (SPEC-v3 §6.2); есть, если ресурс доступен на запись */
  action?: ModuleAction;
}

export const DEFAULT_TABS: readonly PanelTab[] = [
  { key: "card" },
  { key: "chat" },
  { key: "documents" },
];
