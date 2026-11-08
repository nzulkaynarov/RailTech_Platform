import {
  Building2,
  ClipboardCheck,
  ClipboardList,
  FileSignature,
  FileText,
  FolderOpen,
  Inbox,
  MessagesSquare,
  Package,
  PackageOpen,
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
 * «Запросы» и «Каталог» — один модуль `catalog_requests`. Модуль, которого нет в этом списке, меню не рисует.
 * `group` — раздел меню при двух ролях сразу (клиент и партнёр): «Покупаю» / «Поставляю» / «Компания» (PART-2);
 * с одной ролью меню плоское и прежнее.
 */
export interface NavItem {
  to: string;
  labelKey: string;
  icon: LucideIcon;
  module: string;
  primary?: boolean;
  group: NavGroupKey;
}

export type NavGroupKey = 'buy' | 'supply' | 'account';

export const NAV_ITEMS: NavItem[] = [
  {
    // «Мои товары» партнёра (PART-2): первым — главное рабочее место партнёра; у клиента модуля нет, его меню не меняется
    to: '/my-products',
    labelKey: 'nav.myProducts',
    icon: PackageOpen,
    module: 'my_products',
    group: 'supply',
    primary: true,
  },
  {
    to: '/partner/orders',
    labelKey: 'nav.partnerOrders',
    icon: ClipboardList,
    module: 'my_products',
    group: 'supply',
    primary: true,
  },
  {
    to: '/requests',
    labelKey: 'nav.requests',
    icon: Inbox,
    module: 'catalog_requests',
    group: 'buy',
    primary: true,
  },
  {
    to: '/quotes',
    labelKey: 'nav.quotes',
    icon: FileText,
    module: 'quotes',
    group: 'buy',
    primary: true,
  },
  {
    to: '/catalog',
    labelKey: 'nav.catalog',
    icon: Package,
    module: 'catalog_requests',
    group: 'buy',
    primary: true,
  },
  {
    to: '/documents',
    labelKey: 'nav.documents',
    icon: FolderOpen,
    module: 'documents',
    group: 'buy',
    primary: true,
  },
  {
    to: '/contracts',
    labelKey: 'nav.contracts',
    icon: FileSignature,
    module: 'contracts',
    group: 'buy',
  },
  {
    to: '/invoices',
    labelKey: 'nav.invoices',
    icon: Receipt,
    module: 'invoices',
    group: 'buy',
  },
  { to: '/acts', labelKey: 'nav.acts', icon: ClipboardCheck, module: 'acts', group: 'buy' },
  {
    to: '/deliveries',
    labelKey: 'nav.deliveries',
    icon: Truck,
    module: 'deliveries',
    group: 'buy',
  },
  // Чат кабинета (CHAT-1, ADR-0023): модуль `messages` есть у клиента и партнёра и не выключается; бейдж — `/me.unread`
  {
    to: '/messages',
    labelKey: 'nav.messages',
    icon: MessagesSquare,
    module: 'messages',
    // при двух ролях — в «Компании»: беседа компании с нами одна и о покупках, и о поставках (карта пути контрагента)
    group: 'account',
  },
  {
    to: '/company',
    labelKey: 'nav.company',
    icon: Building2,
    module: 'company',
    group: 'account',
  },
  { to: '/team', labelKey: 'nav.team', icon: Users, module: 'team', group: 'account' },
  {
    to: '/profile',
    labelKey: 'nav.profile',
    icon: UserRound,
    module: 'profile',
    group: 'account',
  },
];

/** Модуль, который есть у любой сессии (выход и язык): сам по себе разделов не открывает (ADR-0022). */
export const PROFILE_MODULE = 'profile';
/** Чат кабинета (CHAT-1): пункт меню с бейджем непрочитанного, «Написать менеджеру» ведёт сюда. */
export const MESSAGES_MODULE = 'messages';

/** Раздел меню при двух ролях: «Покупаю» (клиентские разделы), «Поставляю» («Мои товары»), «Компания» (компания, команда, профиль). */
export interface NavGroup {
  key: NavGroupKey;
  /** Ключ i18n заголовка раздела (`nav.groups.*`). */
  labelKey: string;
  items: NavItem[];
}

export interface Nav {
  /** Пункты, доступные сессии, в порядке меню. */
  items: NavItem[];
  /** Рабочие разделы — без «Профиля»: нет ни одного, значит разделы компании ещё настраиваются. */
  work: NavItem[];
  primary: NavItem[];
  secondary: NavItem[];
  /**
   * Разделы «Покупаю / Поставляю / Компания» — только у компании с обеими ролями (клиент и партнёр) и разделами в обеих
   * группах; иначе `null`, и меню плоское, как у клиента без партнёрской роли (у него ничего не изменилось).
   */
  groups: NavGroup[] | null;
}

const GROUP_ORDER: ReadonlyArray<{ key: NavGroupKey; labelKey: string }> = [
  { key: 'buy', labelKey: 'nav.groups.buy' },
  { key: 'supply', labelKey: 'nav.groups.supply' },
  { key: 'account', labelKey: 'nav.groups.account' },
];

/** Нижняя навигация телефона при двух ролях: по одному главному разделу «Покупаю» и «Поставляю» плюс запросы и КП. */
const GROUPED_PRIMARY = new Set(['/requests', '/quotes', '/catalog', '/my-products']);

/**
 * Меню сессии из `/me.modules`: известные Cabinet модули в порядке `NAV_ITEMS`, незнакомые пропускаются.
 * `roles` (`/me.roles`) нужны для одного: при обеих ролях меню делится на «Покупаю» и «Поставляю».
 */
export function navFor(modules: readonly string[] | undefined, roles: readonly string[] | undefined = []): Nav {
  const allowed = new Set(modules ?? []);
  const items = NAV_ITEMS.filter((item) => allowed.has(item.module));
  const dual = roles.includes('client') && roles.includes('partner');
  const groups = dual
    ? GROUP_ORDER.map(({ key, labelKey }) => ({ key, labelKey, items: items.filter((item) => item.group === key) }))
    : null;
  const grouped = groups !== null && ['buy', 'supply'].every((key) => groups.some((group) => group.key === key && group.items.length > 0));
  const ordered = grouped ? groups.flatMap((group) => group.items) : items;
  const primary = (item: NavItem) => (grouped ? GROUPED_PRIMARY.has(item.to) : Boolean(item.primary));
  return {
    items: ordered,
    work: ordered.filter((item) => item.module !== PROFILE_MODULE),
    primary: ordered.filter(primary),
    secondary: ordered.filter((item) => !primary(item)),
    groups: grouped ? groups.filter((group) => group.items.length > 0) : null,
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
