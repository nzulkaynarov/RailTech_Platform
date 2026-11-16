import {
  Building2,
  ClipboardCheck,
  ClipboardList,
  FileSignature,
  FileText,
  FolderOpen,
  Inbox,
  Mail,
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
 * Разделы кабинета (ARCHITECTURE §5). Нижняя навигация телефона — четыре главных раздела роли (`navFor`), остальные —
 * в «Ещё». На десктопе боковая навигация показывает всё, по блокам.
 * `labelKey` — ключ i18n `nav.*`; полнота ключей проверяется тестом оболочки.
 * `module` — код модуля из `GET /me` (`modules`, ADR-0022): пункт рисуется, только если модуль есть у сессии;
 * «Запросы» и «Каталог» — один модуль `catalog_requests`. Модуль, которого нет в этом списке, меню не рисует.
 * `group` — блок меню (владелец 2026-11-16, план §3d ЛИД-1): «Покупаю» (клиент), «Продаю» (партнёр), «Документы» и
 * «Компания» — у любой роли одни и те же; блок без доступных пунктов не показывается.
 */
export interface NavItem {
  to: string;
  labelKey: string;
  icon: LucideIcon;
  module: string;
  group: NavGroupKey;
}

export type NavGroupKey = 'buy' | 'sell' | 'documents' | 'company';

export const NAV_ITEMS: NavItem[] = [
  {
    // «Мои товары» партнёра (PART-2): первым — главное рабочее место партнёра; у клиента модуля нет, его меню не меняется
    to: '/my-products',
    labelKey: 'nav.myProducts',
    icon: PackageOpen,
    module: 'my_products',
    group: 'sell',
  },
  {
    to: '/partner/orders',
    labelKey: 'nav.partnerOrders',
    icon: ClipboardList,
    module: 'my_products',
    group: 'sell',
  },
  {
    to: '/requests',
    labelKey: 'nav.requests',
    icon: Inbox,
    module: 'catalog_requests',
    group: 'buy',
  },
  {
    to: '/quotes',
    labelKey: 'nav.quotes',
    icon: FileText,
    module: 'quotes',
    group: 'buy',
  },
  {
    to: '/catalog',
    labelKey: 'nav.catalog',
    icon: Package,
    module: 'catalog_requests',
    group: 'buy',
  },
  {
    to: '/contracts',
    labelKey: 'nav.contracts',
    icon: FileSignature,
    module: 'contracts',
    group: 'documents',
  },
  {
    to: '/invoices',
    labelKey: 'nav.invoices',
    icon: Receipt,
    module: 'invoices',
    group: 'documents',
  },
  { to: '/acts', labelKey: 'nav.acts', icon: ClipboardCheck, module: 'acts', group: 'documents' },
  { to: '/letters', labelKey: 'nav.letters', icon: Mail, module: 'letters', group: 'documents' },
  {
    to: '/documents',
    labelKey: 'nav.allDocuments',
    icon: FolderOpen,
    module: 'documents',
    group: 'documents',
  },
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
    group: 'company',
  },
  {
    to: '/company',
    labelKey: 'nav.company',
    icon: Building2,
    module: 'company',
    group: 'company',
  },
  { to: '/team', labelKey: 'nav.team', icon: Users, module: 'team', group: 'company' },
  {
    to: '/profile',
    labelKey: 'nav.profile',
    icon: UserRound,
    module: 'profile',
    group: 'company',
  },
];

/** Модуль, который есть у любой сессии (выход и язык): сам по себе разделов не открывает (ADR-0022). */
export const PROFILE_MODULE = 'profile';
/** Чат кабинета (CHAT-1): пункт меню с бейджем непрочитанного, «Написать менеджеру» ведёт сюда. */
export const MESSAGES_MODULE = 'messages';

/** Блок меню: «Покупаю», «Продаю», «Документы», «Компания» (план §3d ЛИД-1). */
export interface NavGroup {
  key: NavGroupKey;
  /** Ключ i18n заголовка блока (`nav.groups.*`). */
  labelKey: string;
  items: NavItem[];
}

export interface Nav {
  /** Пункты, доступные сессии, в порядке меню (по блокам). */
  items: NavItem[];
  /** Рабочие разделы — без «Профиля»: нет ни одного, значит разделы компании ещё настраиваются. */
  work: NavItem[];
  /** Нижняя навигация телефона: до четырёх главных разделов роли. */
  primary: NavItem[];
  secondary: NavItem[];
  /** Блоки меню, только непустые; у любой роли одна структура, роль добавляет свой рабочий блок. */
  groups: NavGroup[];
}

const GROUP_LABELS: Record<NavGroupKey, string> = {
  buy: 'nav.groups.buy',
  sell: 'nav.groups.sell',
  documents: 'nav.groups.documents',
  company: 'nav.groups.company',
};

/** Нижняя навигация телефона: главные разделы роли, первые четыре доступных. */
const PRIMARY_CLIENT = ['/requests', '/quotes', '/catalog', '/documents'];
const PRIMARY_DUAL = ['/requests', '/quotes', '/catalog', '/my-products'];
const PRIMARY_PARTNER = ['/my-products', '/partner/orders', '/requests', '/catalog'];
const PRIMARY_LIMIT = 4;

/**
 * Меню сессии из `/me.modules`: известные Cabinet модули по блокам, незнакомые пропускаются. `roles` (`/me.roles`) задают
 * порядок: у клиента первым «Покупаю», у партнёра без клиентской роли — «Продаю»; «Документы» и «Компания» — следом.
 */
export function navFor(modules: readonly string[] | undefined, roles: readonly string[] | undefined = []): Nav {
  const allowed = new Set(modules ?? []);
  const available = NAV_ITEMS.filter((item) => allowed.has(item.module));
  const client = roles.includes('client') || !roles.includes('partner');
  const order: NavGroupKey[] = client ? ['buy', 'sell', 'documents', 'company'] : ['sell', 'buy', 'documents', 'company'];
  const groups = order
    .map((key) => ({ key, labelKey: GROUP_LABELS[key], items: available.filter((item) => item.group === key) }))
    .filter((group) => group.items.length > 0);
  const items = groups.flatMap((group) => group.items);
  const dual = roles.includes('client') && roles.includes('partner') && items.some((item) => item.group === 'sell');
  const wanted = dual ? PRIMARY_DUAL : client ? PRIMARY_CLIENT : PRIMARY_PARTNER;
  const primaryTo = new Set(wanted.filter((to) => items.some((item) => item.to === to)).slice(0, PRIMARY_LIMIT));
  return {
    items,
    work: items.filter((item) => item.module !== PROFILE_MODULE),
    primary: items.filter((item) => primaryTo.has(item.to)),
    secondary: items.filter((item) => !primaryTo.has(item.to)),
    groups,
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
