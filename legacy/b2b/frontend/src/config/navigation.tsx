/**
 * ADR-0005 — единый, config-driven навигационный стандарт (Phase A).
 *
 * ОДИН источник навигации для tenant-shell вместо трёх захардкоженных по персоне
 * (getBuyerNavigation/getSellerNavigation/...). Объектная IA (Главная · Сделки · Документы ·
 * Номенклатура · Настройки); направление (Полученные/Отправленные) — фильтр ВНУТРИ страниц, не
 * отдельные разделы. Каждый пункт декларирует `requires` (capability) — движок ПРЯЧЕТ (не
 * дизейблит) то, что не выдано (мировой стандарт: Budibase/Oso). Гейтинг здесь = только UX;
 * бэкенд-enforcement (member_has_permission / подписка / KYC-floor) остаётся независимым.
 *
 * `side` сохраняет текущий контекст-свитчер Покупатель↔Продавец как фильтр (Phase C сольёт
 * shell и уберёт свитчер). Цели (`id`) указывают на СУЩЕСТВУЮЩИЕ страницы — мы унифицируем
 * навигацию, не переписываем страницы.
 */
import {
  LayoutDashboard, Package, ClipboardList, Handshake, Receipt,
  FileText, Boxes, Settings, HelpCircle,
} from 'lucide-react';
import type { Capabilities, CompanyStatus } from '@/store/userStore';

/** Per-item capability gate. All present conditions must hold (AND). */
export interface NavRequirement {
  kyc?: boolean;          // company KYC must be verified (L2+)
  subscription?: boolean; // seller company must have an operational subscription
  anyPerm?: string[];     // member must hold AT LEAST ONE of these company permissions
}

type Side = 'buy' | 'sell' | 'both';

export interface NavNodeDef {
  labelKey: string;
  id?: string;            // page hash (leaf)
  icon?: React.ReactNode;
  side?: Side;            // which context shows it (default 'both')
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

// KYC codes that count as "verified" for capability gating (L2 floor; L3 is higher).
const KYC_VERIFIED = new Set(['L2_VERIFIED', 'L3_VERIFIED']);

export function isKycVerified(level: string | null | undefined): boolean {
  return !!level && KYC_VERIFIED.has(level);
}

/** True if `caps` satisfies a node's requirement (a buyer/seller capability check, NOT security). */
function meetsRequirement(req: NavRequirement | undefined, caps: Capabilities): boolean {
  if (!req) return true;
  if (req.kyc && !isKycVerified(caps.kyc_level)) return false;
  if (req.subscription && !caps.subscription_active) return false;
  // Perm-gate only when we actually HAVE permission data — an empty list means "unknown"
  // (old /me payload, or a member pre-backfill) → don't over-hide; the backend still enforces.
  if (req.anyPerm && req.anyPerm.length > 0 && caps.permissions.length > 0) {
    if (!req.anyPerm.some((perm) => caps.permissions.includes(perm))) return false;
  }
  return true;
}

function sideAllowed(side: Side | undefined, context: CompanyStatus): boolean {
  if (!side || side === 'both') return true;
  if (side === 'buy') return context === 'BUYER';
  return context === 'SELLER';
}

/**
 * The canonical tenant nav (object-based). Targets reference existing pages; grouping +
 * `requires` are the unification. Direction (Полученные/Отправленные) is a page-level filter.
 */
export const TENANT_NAV: NavNodeDef[] = [
  { labelKey: 'shell.dashboard', id: 'dashboard', icon: <LayoutDashboard className="h-4 w-4" /> },

  // Сделки — единый объект; в контексте Покупатель → мои заявки, Продавец → CRM-сделки.
  { labelKey: 'shell.deals', id: 'my-requests', icon: <ClipboardList className="h-4 w-4" />, side: 'buy', requires: { kyc: true, anyPerm: ['request.create', 'quote.approve'] } },
  { labelKey: 'shell.deals', id: 'crm-deals', icon: <Handshake className="h-4 w-4" />, side: 'sell', requires: { anyPerm: ['quote.build', 'quote.send'] } },

  // Документы — КП · Договоры · Счета · Акты (фильтр направления — на самих страницах).
  {
    labelKey: 'shell.documents', icon: <FileText className="h-4 w-4" />,
    children: [
      { labelKey: 'shell.quotes', id: 'crm-quotes', side: 'sell', requires: { anyPerm: ['quote.build', 'quote.send'] } },
      { labelKey: 'shell.contracts', id: 'contracts' },
      { labelKey: 'shell.invoices', id: 'invoices' },
      { labelKey: 'shell.payments', id: 'payments' },
      { labelKey: 'shell.acts', id: 'acts', side: 'sell' },
      { labelKey: 'shell.fulfillments', id: 'fulfillments' },
    ],
  },

  // Номенклатура — Товары · Справочники (Клиенты — Phase F). Покупатель видит каталог read-only.
  { labelKey: 'shell.catalog', id: 'products', icon: <Package className="h-4 w-4" />, side: 'buy' },
  {
    labelKey: 'shell.nomenclatureSection', icon: <Boxes className="h-4 w-4" />, side: 'sell',
    requires: { anyPerm: ['catalog.manage', 'catalog.publish'] },
    children: [
      { labelKey: 'shell.nomenclature', id: 'products' },
      { labelKey: 'shell.categories', id: 'categories' },
      { labelKey: 'shell.equipmentGroups', id: 'equipment-groups' },
      { labelKey: 'shell.catalogImport', id: 'catalog-import' },
    ],
  },

  // Подписка — seller billing entry that isn't a "document".
  { labelKey: 'shell.mySubscription', id: 'my-subscription', icon: <Receipt className="h-4 w-4" />, side: 'sell' },
];

export const TENANT_BOTTOM_NAV: NavNodeDef[] = [
  { labelKey: 'shell.settings', id: 'settings', icon: <Settings className="h-4 w-4" /> },
  { labelKey: 'shell.help', id: 'help', icon: <HelpCircle className="h-4 w-4" /> },
];

type TFn = (key: string) => string;

/**
 * Resolve a nav definition into rendered items for the active context, HIDING anything the
 * user's capabilities don't satisfy. Empty parent groups (all children hidden) are dropped.
 */
export function buildNavigation(
  defs: NavNodeDef[],
  caps: Capabilities,
  context: CompanyStatus,
  activePage: string,
  t: TFn,
): ResolvedNavItem[] {
  const items: ResolvedNavItem[] = [];
  for (const def of defs) {
    if (!sideAllowed(def.side, context) || !meetsRequirement(def.requires, caps)) continue;

    if (def.children) {
      const children: ResolvedNavChild[] = def.children
        .filter((child) => sideAllowed(child.side, context) && meetsRequirement(child.requires, caps))
        .map((child) => ({ label: t(child.labelKey), id: child.id as string, active: activePage === child.id }));
      if (children.length === 0) continue; // never render an empty group
      items.push({ label: t(def.labelKey), icon: def.icon, children });
    } else {
      items.push({ label: t(def.labelKey), icon: def.icon, id: def.id, active: activePage === def.id });
    }
  }
  return items;
}
