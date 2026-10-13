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
  LayoutDashboard, Package, ClipboardList, Handshake,
  FileText, Boxes, Settings, HelpCircle, Users, Truck,
} from 'lucide-react';
import type { Capabilities } from '@/store/userStore';

/** Per-item capability gate. All present conditions must hold (AND). */
export interface NavRequirement {
  kyc?: boolean;          // company KYC must be verified (L2+)
  subscription?: boolean; // seller company must have an operational subscription
  anyPerm?: string[];     // member must hold AT LEAST ONE of these company permissions
}

type Side = 'buy' | 'sell' | 'both';

/**
 * The sides a company is CAPABLE of (a verified BUYER entry → buy; a verified
 * SUPPLIER/MANUFACTURER entry → sell). Phase C unifies the shell: nav visibility
 * follows capability (a dual company sees BOTH sides at once), replacing the old
 * Покупатель↔Продавец switcher that showed one transient side at a time. The
 * active data-context (X-Active-Context header) now follows the PAGE, not a toggle.
 */
export interface CapableSides {
  buy: boolean;
  sell: boolean;
}

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
// The seeded VerificationStatus codes are L2_VERIFIED and L3_CONTRACTED (see
// backend/core/migrations/0002_seed_enterprise_lookups.py + accounts/constants.py);
// there is no `L3_VERIFIED` code — it was a phantom that hid every kyc-gated nav
// item from L3_CONTRACTED companies. userStore.ts already treats both as verified.
const KYC_VERIFIED = new Set(['L2_VERIFIED', 'L3_CONTRACTED']);

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

function sideAllowed(side: Side | undefined, sides: CapableSides): boolean {
  if (!side || side === 'both') return true;
  if (side === 'buy') return sides.buy;
  return sides.sell;
}

/**
 * The canonical tenant nav (object-based). Targets reference existing pages; grouping +
 * `requires` are the unification. Direction (Полученные/Отправленные) is a page-level filter.
 */
export const TENANT_NAV: NavNodeDef[] = [
  { labelKey: 'shell.dashboard', id: 'dashboard', icon: <LayoutDashboard className="h-4 w-4" /> },

  // Сделки — в unified shell обе стороны видны сразу у dual-компании, поэтому у них
  // РАЗНЫЕ ярлыки: закупочная сторона → «Мои заявки», продающая → «Сделки» (CRM).
  { labelKey: 'shell.myRequests', id: 'my-requests', icon: <ClipboardList className="h-4 w-4" />, side: 'buy', requires: { kyc: true, anyPerm: ['request.create', 'quote.approve'] } },
  { labelKey: 'shell.deals', id: 'crm-deals', icon: <Handshake className="h-4 w-4" />, side: 'sell', requires: { kyc: true, anyPerm: ['quote.build', 'quote.send'] } },

  // Книга контрагентов (CRM Phase B) — симметрична: продающая сторона видит «Клиентов»,
  // закупочная — «Поставщиков». Отношение с историей = T1 (KYC L2+) продуктовый слой.
  { labelKey: 'counterparties.title.clients', id: 'clients', icon: <Users className="h-4 w-4" />, side: 'sell', requires: { kyc: true } },
  { labelKey: 'counterparties.title.suppliers', id: 'suppliers', icon: <Truck className="h-4 w-4" />, side: 'buy', requires: { kyc: true } },

  // Документы — КП · Договоры · Счета · Акты (фильтр направления — на самих страницах).
  // ADR-0005 tier table: every document surface is a T1/T2 (KYC L2+) action — a T0
  // (KYC-pending) user only gets Главная/Профиль/каталог-read. Each child carries
  // kyc:true so the group is HIDDEN pre-KYC, matching the App.tsx KYC_ALLOWED_PAGES
  // guard (which bounces these pages) — no shown-but-bounced items.
  {
    labelKey: 'shell.documents', icon: <FileText className="h-4 w-4" />,
    children: [
      { labelKey: 'shell.quotes', id: 'crm-quotes', side: 'sell', requires: { kyc: true, anyPerm: ['quote.build', 'quote.send'] } },
      { labelKey: 'shell.contracts', id: 'contracts', requires: { kyc: true } },
      { labelKey: 'shell.invoices', id: 'invoices', requires: { kyc: true } },
      { labelKey: 'shell.payments', id: 'payments', requires: { kyc: true } },
      // Акт двусторонний: заказчик его принимает или возвращает. Пункт без `side` — как у
      // договоров, счетов и отгрузок; список сужен видимостью на бэкенде (U1).
      { labelKey: 'shell.acts', id: 'acts', requires: { kyc: true } },
      { labelKey: 'shell.fulfillments', id: 'fulfillments', requires: { kyc: true } },
      { labelKey: 'shell.otherDocuments', id: 'other-documents', requires: { kyc: true } },
      { labelKey: 'shell.files', id: 'company-files', requires: { kyc: true } },
    ],
  },

  // Номенклатура — Товары · Справочники (Клиенты — Phase F). Покупатель видит каталог read-only.
  // Каталог (products) stays UNGATED — ADR-0005 T0 explicitly allows catalog-read pre-KYC.
  { labelKey: 'shell.catalog', id: 'products', icon: <Package className="h-4 w-4" />, side: 'buy' },
  {
    labelKey: 'shell.nomenclatureSection', icon: <Boxes className="h-4 w-4" />, side: 'sell',
    // НАПОЛНЕНИЕ каталога доступно до верификации, ПУБЛИКАЦИЯ — нет.
    //
    // Эталон Amazon Seller Central: пока идёт проверка аккаунта, продавец готовит листинги, а
    // живыми они становятся после неё. Раньше `kyc: true` прятал раздел целиком, и новый
    // продавец не мог ни завести карточку, ни загрузить прайс, пока оператор не проверит
    // документы, — то есть простаивал ровно в тот момент, когда готов работать.
    //
    // Гейт не исчез, а переехал на само действие: `catalog/publishing.py` возвращает
    // `SELLER_KYC_REQUIRED`. Прав стало строго больше — ничего из работавшего не отнято.
    requires: { anyPerm: ['catalog.manage', 'catalog.publish'] },
    // Целевая структура аудита §5.1: «Товары → Мои товары / Загрузка прайса / Справочники».
    // «Номенклатуры» в трёх смыслах больше нет: раздел назван по объекту, единственный
    // «Каталог» — витрина покупателя (верхний пункт side: buy). Дубль «Каталога» у компании,
    // которая и покупает, и продаёт, ушёл вместе с этим. Старые хэши живы алиасами.
    children: [
      { labelKey: 'shell.myProducts', id: 'my-products' },
      { labelKey: 'shell.catalogImport', id: 'catalog-import' },
      { labelKey: 'shell.catalogReference', id: 'catalog-reference' },
    ],
  },

  // «Подписка» перенесена в Настройки → Биллинг (S5/P7) — top-level пункт убран. Роут
  // #my-subscription остаётся рабочим (App.tsx) для старых ссылок/закладок, но в меню его нет.
];

// Профиль слился с Настройками в единый Settings Hub (settings-profile-redesign §2.1):
// пункт profile убран, `#profile` остаётся алиасом на `#settings?section=profile` (App.tsx).
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
  sides: CapableSides,
  activePage: string,
  t: TFn,
): ResolvedNavItem[] {
  const items: ResolvedNavItem[] = [];
  for (const def of defs) {
    if (!sideAllowed(def.side, sides) || !meetsRequirement(def.requires, caps)) continue;

    if (def.children) {
      const children: ResolvedNavChild[] = def.children
        .filter((child) => sideAllowed(child.side, sides) && meetsRequirement(child.requires, caps))
        .map((child) => ({ label: t(child.labelKey), id: child.id as string, active: activePage === child.id }));
      if (children.length === 0) continue; // never render an empty group
      items.push({ label: t(def.labelKey), icon: def.icon, children });
    } else {
      items.push({ label: t(def.labelKey), icon: def.icon, id: def.id, active: activePage === def.id });
    }
  }
  return items;
}
