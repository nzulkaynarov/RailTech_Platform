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
 * `module` — код модуля из `GET /me` (`modules`, ADR-0022): пункт рисуется, только если модуль есть у сессии;
 * «Запросы» и «Каталог» — один модуль `catalog_requests`. Модуль, которого нет в этом списке (например `my_products`,
 * пока у него нет раздела), меню не рисует.
 */
export interface NavItem {
  to: string;
  labelKey: string;
  icon: LucideIcon;
  module: string;
  primary?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  {
    to: '/requests',
    labelKey: 'nav.requests',
    icon: Inbox,
    module: 'catalog_requests',
    primary: true,
  },
  {
    to: '/quotes',
    labelKey: 'nav.quotes',
    icon: FileText,
    module: 'quotes',
    primary: true,
  },
  {
    to: '/catalog',
    labelKey: 'nav.catalog',
    icon: Package,
    module: 'catalog_requests',
    primary: true,
  },
  {
    to: '/documents',
    labelKey: 'nav.documents',
    icon: FolderOpen,
    module: 'documents',
    primary: true,
  },
  {
    to: '/contracts',
    labelKey: 'nav.contracts',
    icon: FileSignature,
    module: 'contracts',
  },
  {
    to: '/invoices',
    labelKey: 'nav.invoices',
    icon: Receipt,
    module: 'invoices',
  },
  { to: '/acts', labelKey: 'nav.acts', icon: ClipboardCheck, module: 'acts' },
  {
    to: '/deliveries',
    labelKey: 'nav.deliveries',
    icon: Truck,
    module: 'deliveries',
  },
  {
    to: '/company',
    labelKey: 'nav.company',
    icon: Building2,
    module: 'company',
  },
  { to: '/team', labelKey: 'nav.team', icon: Users, module: 'team' },
  {
    to: '/profile',
    labelKey: 'nav.profile',
    icon: UserRound,
    module: 'profile',
  },
];

/** Модуль, который есть у любой сессии (выход и язык): сам по себе разделов не открывает (ADR-0022). */
export const PROFILE_MODULE = 'profile';

export interface Nav {
  /** Пункты, доступные сессии, в порядке меню. */
  items: NavItem[];
  /** Рабочие разделы — без «Профиля»: нет ни одного, значит разделы компании ещё настраиваются. */
  work: NavItem[];
  primary: NavItem[];
  secondary: NavItem[];
}

/** Меню сессии из `/me.modules`: известные Cabinet модули в порядке `NAV_ITEMS`, незнакомые пропускаются. */
export function navFor(modules: readonly string[] | undefined): Nav {
  const allowed = new Set(modules ?? []);
  const items = NAV_ITEMS.filter((item) => allowed.has(item.module));
  return {
    items,
    work: items.filter((item) => item.module !== PROFILE_MODULE),
    primary: items.filter((item) => item.primary),
    secondary: items.filter((item) => !item.primary),
  };
}

/** Раздел по адресу: пункт меню, под которым лежит страница (`/quotes/301` → «КП»); `undefined` — адрес вне меню. */
export function navItemFor(pathname: string): NavItem | undefined {
  // «Проект» (`/deals/:id`) собирает КП, договоры, счета и акты — открыт тем, у кого есть КП
  if (isWithin(pathname, '/deals')) return NAV_ITEMS.find((item) => item.module === 'quotes');
  return NAV_ITEMS.find((item) => isWithin(pathname, item.to));
}

/** Корни разделов: на них в Mini App кнопка «Назад» Telegram скрыта. */
export function isSectionRoot(pathname: string): boolean {
  return pathname === '/' || NAV_ITEMS.some((item) => item.to === pathname);
}

export function isWithin(pathname: string, to: string): boolean {
  return pathname === to || pathname.startsWith(`${to}/`);
}
