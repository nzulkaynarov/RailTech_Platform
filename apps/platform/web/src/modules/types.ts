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
  /**
   * Пункт подменю виден, пока выполняется условие (W15-H4): `setupPending` — «Первый запуск» до завершения всех шагов
   * мастера; потом экран открывается ссылкой «Настройка Платформы» в «Подключениях». Раздел остаётся в меню каталога.
   */
  showWhile?: "setupPending";
  /** Пункт подменю, который подсвечивается, когда открыт этот (скрытый) раздел: «Обмен между системами» — часть «Журнала» */
  parent?: string;
  /**
   * Кому раздел виден в подменю, если это уже, чем доступ к адресу (W15-H4): «База знаний бота» в Клиентах — менеджеру
   * на чтение; администратор входит в неё из Настроек · Telegram-бот, адрес для него остаётся открытым.
   */
  menuAccess?: AccessRule;
  /**
   * Где раздел живёт в меню для того, кому его пункт в своём модуле не виден (`menuAccess`): подменю и крошки этого
   * модуля с подсвеченным пунктом. «База знаний бота» для администратора — Настройки · Telegram-бот (W15-H4).
   */
  menuHome?: { module: ModuleCode; section: string };
  /** Вкладки бокового окна; первая — по действию экрана (SPEC-v3 §6.1). По умолчанию — Карточка · Чат проекта · Документы */
  tabs?: readonly PanelTab[];
  /**
   * Панели по умолчанию (SPEC-v3 §6.1): `menuOpen` — подменю на ≥ 1440 px; `panelOpen: false` — окно закрыто и на карточке
   * объекта (в списках оно закрыто всегда, ORCHESTRATOR §3 п. 18); `panelMode: "docked"` — раздел, где окно нужно рядом с
   * работой (переписка): на ≥ 1280 px оно закреплено, а не поверх.
   */
  defaults?: { menuOpen?: boolean; panelOpen?: boolean; panelMode?: "overlay" | "docked" };
  /** Куда ведёт действие пустого состояния; без поля — кнопка неактивна («появится в фазе P2») */
  actionTo?: string;
  /** < 768 px боковое окно раздела — лист на весь экран (B-020), а не узкое окно справа */
  sheetOnMobile?: boolean;
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
