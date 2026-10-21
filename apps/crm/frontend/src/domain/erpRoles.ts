/**
 * Системные роли бэк-офиса ERP, которые админ выдаёт из CRM (FIX-63, Q-FIX50-1 (1)).
 *
 * Коды — `SystemRoleCode` контракта (`erp-integration.yaml`), порядок — как в «Настройках → Команда» ERP. Права
 * ролей ведёт ERP, здесь только коды и названия на трёх языках (CLAUDE.md §4: тексты — ru/uz/en). Интерфейс CRM
 * пока на русском, поэтому по умолчанию показывается `ru`.
 */
import type { UserOutErpRoleCodesItem } from "../api/generated/model";

export const ERP_ROLE_CODES = [
  "CALCULATION",
  "CATALOG_SUPPLY",
  "FULFILLMENT",
  "FINANCE",
  "HEAD",
  "VIEWER",
] as const satisfies readonly UserOutErpRoleCodesItem[];

export type ErpRoleCode = (typeof ERP_ROLE_CODES)[number];
type Language = "ru" | "uz" | "en";
type Texts = Record<Language, string>;

export const ERP_ROLE_LABELS: Record<ErpRoleCode, { name: Texts; hint: Texts }> = {
  CALCULATION: {
    name: { ru: "Расчёт", uz: "Hisob-kitob", en: "Calculation" },
    hint: {
      ru: "Сделки, КП и цены, отправка КП, договоры",
      uz: "Bitimlar, tijoriy takliflar va narxlar, takliflarni yuborish, shartnomalar",
      en: "Deals, quotes and pricing, sending quotes, contracts",
    },
  },
  CATALOG_SUPPLY: {
    name: { ru: "Каталог и закупки", uz: "Katalog va xaridlar", en: "Catalog and procurement" },
    hint: {
      ru: "Каталог и публикация, предложения поставщиков, себестоимость",
      uz: "Katalog va nashr etish, yetkazib beruvchilar takliflari, tannarx",
      en: "Catalog and publishing, supplier offers, cost price",
    },
  },
  FULFILLMENT: {
    name: {
      ru: "Исполнение и логистика",
      uz: "Ijro va logistika",
      en: "Fulfillment and logistics",
    },
    hint: {
      ru: "Поставки, отгрузки и акты приёмки",
      uz: "Yetkazib berish, jo'natish va qabul dalolatnomalari",
      en: "Deliveries, shipments and acceptance acts",
    },
  },
  FINANCE: {
    name: { ru: "Финансы", uz: "Moliya", en: "Finance" },
    hint: {
      ru: "Счета, оплаты, курсы валют, выгрузка данных",
      uz: "Hisob-fakturalar, to'lovlar, valyuta kurslari, ma'lumotlarni eksport qilish",
      en: "Invoices, payments, exchange rates, data export",
    },
  },
  HEAD: {
    name: { ru: "Руководитель", uz: "Rahbar", en: "Head" },
    hint: {
      ru: "Все права: финальное утверждение КП, подпись договора, команда и настройки",
      uz: "Barcha huquqlar: takliflarni yakuniy tasdiqlash, shartnomani imzolash, jamoa va sozlamalar",
      en: "All rights: final quote approval, contract signing, team and settings",
    },
  },
  VIEWER: {
    name: { ru: "Наблюдатель", uz: "Kuzatuvchi", en: "Viewer" },
    hint: {
      ru: "Только просмотр, без изменений",
      uz: "Faqat ko'rish, o'zgartirishsiz",
      en: "View only, no changes",
    },
  },
};

const isCode = (code: string): code is ErpRoleCode => code in ERP_ROLE_LABELS;

export const erpRoleLabel = (code: string, language: Language = "ru"): string =>
  isCode(code) ? ERP_ROLE_LABELS[code].name[language] : code;

export const erpRoleHint = (code: string, language: Language = "ru"): string =>
  isCode(code) ? ERP_ROLE_LABELS[code].hint[language] : "";

/** Варианты мультивыбора: подпись — название, всплывающая подсказка — что роль разрешает. */
export const erpRoleOptions = (language: Language = "ru") =>
  ERP_ROLE_CODES.map((value) => ({
    value,
    label: erpRoleLabel(value, language),
    title: erpRoleLabel(value, language),
    hint: erpRoleHint(value, language),
  }));

/** Выбранные роли ERP пользователя; нет поля (старый ответ) — пусто. */
export const erpRolesOf = (
  user: { erp_role_codes?: readonly string[] | undefined } | null | undefined,
): string[] => [...(user?.erp_role_codes ?? [])];

/** Роль CRM «admin» — суперпользователь ERP: системные роли ему не нужны (ERP их игнорирует). */
export const isErpSuperuser = (user: { roles: readonly string[] }): boolean =>
  user.roles.includes("admin");
