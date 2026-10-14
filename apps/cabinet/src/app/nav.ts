import {
  Building2,
  ClipboardCheck,
  FileSignature,
  FileText,
  FolderOpen,
  Inbox,
  Package,
  Receipt,
  Truck,
  UserRound,
  Users,
  type LucideIcon,
} from 'lucide-react';

/**
 * Разделы кабинета (ARCHITECTURE §5). `primary` — четыре раздела нижней навигации телефона;
 * остальные — в «Ещё». На десктопе боковая навигация показывает всё.
 * `labelKey` — ключ i18n `nav.*`; полнота ключей проверяется тестом оболочки.
 */
export interface NavItem {
  to: string;
  labelKey: string;
  icon: LucideIcon;
  primary?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/requests', labelKey: 'nav.requests', icon: Inbox, primary: true },
  { to: '/quotes', labelKey: 'nav.quotes', icon: FileText, primary: true },
  { to: '/catalog', labelKey: 'nav.catalog', icon: Package, primary: true },
  { to: '/documents', labelKey: 'nav.documents', icon: FolderOpen, primary: true },
  { to: '/contracts', labelKey: 'nav.contracts', icon: FileSignature },
  { to: '/invoices', labelKey: 'nav.invoices', icon: Receipt },
  { to: '/acts', labelKey: 'nav.acts', icon: ClipboardCheck },
  { to: '/deliveries', labelKey: 'nav.deliveries', icon: Truck },
  { to: '/company', labelKey: 'nav.company', icon: Building2 },
  { to: '/team', labelKey: 'nav.team', icon: Users },
  { to: '/profile', labelKey: 'nav.profile', icon: UserRound },
];

export const PRIMARY_NAV = NAV_ITEMS.filter((item) => item.primary);
export const SECONDARY_NAV = NAV_ITEMS.filter((item) => !item.primary);

/** Корни разделов: на них в Mini App кнопка «Назад» Telegram скрыта. */
export function isSectionRoot(pathname: string): boolean {
  return pathname === '/' || NAV_ITEMS.some((item) => item.to === pathname);
}

export function isWithin(pathname: string, to: string): boolean {
  return pathname === to || pathname.startsWith(`${to}/`);
}
