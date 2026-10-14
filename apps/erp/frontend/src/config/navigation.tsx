/**
 * ADR-0005 — единый, config-driven навигационный стандарт (Phase A).
 *
 * ОДИН источник навигации для tenant-shell вместо трёх захардкоженных по персоне
 * (getBuyerNavigation/getSellerNavigation/...). Объектная IA (Главная · Сделки · Документы ·
 * Номенклатура · Настройки); направление (Полученные/Отправленные) — фильтр ВНУТРИ страниц, не
 * отдельные разделы. Каждый пункт декларирует `requires` (capability) — движок ПРЯЧЕТ (не
 * дизейблит) то, что не выдано (мировой стандарт: Budibase/Oso). Гейтинг здесь = только UX;
 * бэкенд-enforcement (member_has_permission) остаётся независимым.
 *
 * ERP — бэк-офис одной компании. Роли бэк-офиса (M1-ERP-05): ПРОСМОТР открыт любому сотруднику
 * (роль «Наблюдатель» видит всё, BUSINESS §11), поэтому разделы-реестры видны всем; `requires`
 * прячет только пункты-инструменты, которые без права бессмысленны (загрузка прайса —
 * `catalog.manage`). Кнопки действий внутри страниц прячутся по своим кодам прав.
 */
import {
  LayoutDashboard, Handshake,
  FileText, Boxes, Settings, HelpCircle, Users,
} from 'lucide-react';
import type { Capabilities } from '@/store/userStore';

/** Per-item capability gate. All present conditions must hold (AND). */
export interface NavRequirement {
  anyPerm?: string[];     // member must hold AT LEAST ONE of these company permissions
}

export interface NavNodeDef {
  labelKey: string;
  id?: string;            // page hash (leaf)
  icon?: React.ReactNode;
  requires?: NavRequirement;
  children?: NavNodeDef[];
}

export interface ResolvedNavChild { label: string; id: string; active?: boolean }
export interface ResolvedNavItem {
  label: string;
  icon: React.ReactNode;
  id?: string;
  active?: boolean;
  children?: ResolvedNavChild[];
}

/** True if `caps` satisfies a node's requirement (UX only, NOT security — the backend enforces). */
function meetsRequirement(req: NavRequirement | undefined, caps: Capabilities): boolean {
  if (!req) return true;
  // Пустой список прав = прав нет (M1-ERP-05: «Наблюдатель»), а не «неизвестно».
  if (req.anyPerm && req.anyPerm.length > 0) {
    if (!req.anyPerm.some((perm) => caps.permissions.includes(perm))) return false;
  }
  return true;
}

/**
 * The canonical tenant nav (object-based). Targets reference existing pages; grouping +
 * `requires` are the unification. Direction (Полученные/Отправленные) is a page-level filter.
 */
export const TENANT_NAV: NavNodeDef[] = [
  { labelKey: 'shell.dashboard', id: 'dashboard', icon: <LayoutDashboard className="h-4 w-4" /> },

  // Сделки — очередь запросов клиентов, карточка сделки, билдер КП.
  { labelKey: 'shell.deals', id: 'crm-deals', icon: <Handshake className="h-4 w-4" /> },

  // Книга клиентов (CRM Phase B).
  { labelKey: 'counterparties.title.clients', id: 'clients', icon: <Users className="h-4 w-4" /> },

  // Документы — КП · Договоры · Счета · Оплаты · Акты · Отгрузка (со стороны исполнителя).
  {
    labelKey: 'shell.documents', icon: <FileText className="h-4 w-4" />,
    children: [
      { labelKey: 'shell.quotes', id: 'crm-quotes' },
      { labelKey: 'shell.contracts', id: 'contracts' },
      { labelKey: 'shell.invoices', id: 'invoices' },
      { labelKey: 'shell.payments', id: 'payments' },
      { labelKey: 'shell.acts', id: 'acts' },
      { labelKey: 'shell.fulfillments', id: 'fulfillments' },
      { labelKey: 'shell.otherDocuments', id: 'other-documents' },
      { labelKey: 'shell.files', id: 'company-files' },
    ],
  },

  // Товары — Мои товары · Загрузка прайса · Справочники.
  {
    labelKey: 'shell.nomenclatureSection', icon: <Boxes className="h-4 w-4" />,
    children: [
      { labelKey: 'shell.myProducts', id: 'my-products' },
      { labelKey: 'shell.catalogImport', id: 'catalog-import', requires: { anyPerm: ['catalog.manage'] } },
      { labelKey: 'shell.catalogReference', id: 'catalog-reference' },
    ],
  },
];

// Профиль слился с Настройками в единый Settings Hub (settings-profile-redesign §2.1):
// пункт profile убран, `#profile` остаётся алиасом на `#settings?section=profile` (App.tsx).
export const TENANT_BOTTOM_NAV: NavNodeDef[] = [
  { labelKey: 'shell.settings', id: 'settings', icon: <Settings className="h-4 w-4" /> },
  { labelKey: 'shell.help', id: 'help', icon: <HelpCircle className="h-4 w-4" /> },
];

type TFn = (key: string) => string;

/**
 * Resolve a nav definition into rendered items, HIDING anything the
 * user's capabilities don't satisfy. Empty parent groups (all children hidden) are dropped.
 */
export function buildNavigation(
  defs: NavNodeDef[],
  caps: Capabilities,
  activePage: string,
  t: TFn,
): ResolvedNavItem[] {
  const items: ResolvedNavItem[] = [];
  for (const def of defs) {
    if (!meetsRequirement(def.requires, caps)) continue;

    if (def.children) {
      const children: ResolvedNavChild[] = def.children
        .filter((child) => meetsRequirement(child.requires, caps))
        .map((child) => ({ label: t(child.labelKey), id: child.id as string, active: activePage === child.id }));
      if (children.length === 0) continue; // never render an empty group
      items.push({ label: t(def.labelKey), icon: def.icon, children });
    } else {
      items.push({ label: t(def.labelKey), icon: def.icon, id: def.id, active: activePage === def.id });
    }
  }
  return items;
}
