/**
 * Отображение `Page` → содержимое экрана.
 *
 * Все страницы грузятся лениво (`lazyWithRetry`). Подавляющее большинство маршрутов
 * рендерит компонент без пропсов — они собраны таблицей `PLAIN_PAGES`. Явные ветки
 * остались только там, где странице нужны пропсы или где `activePage` шелла отличается
 * от идентификатора маршрута (например `#sourcing-requests` подсвечивает «Сделки»).
 */

import type { ComponentType, ReactNode } from 'react';
import { PAGE_IDS } from '@/config/pageRegistry';
import { lazyWithRetry } from '@/lib/lazyWithRetry';
import type { CompanyStatus } from '@/store/userStore';
import type { Page } from './hashRoute';

const KNOWN_PAGE_IDS = new Set<string>(PAGE_IDS);

const ProductManagement = lazyWithRetry(() =>
  import('@/pages/ProductManagement').then((m) => ({ default: m.ProductManagement })),
);
const ProductDetail = lazyWithRetry(() => import('@/pages/ProductDetail').then((m) => ({ default: m.ProductDetail })));
const NomenclatureQueuePage = lazyWithRetry(() =>
  import('@/pages/NomenclatureQueuePage').then((m) => ({ default: m.NomenclatureQueuePage })),
);
const HSDirectoryPage = lazyWithRetry(() =>
  import('@/pages/HSDirectoryPage').then((m) => ({ default: m.HSDirectoryPage })),
);
const Dashboard = lazyWithRetry(() => import('@/pages/Dashboard').then((m) => ({ default: m.Dashboard })));
const SettingsPage = lazyWithRetry(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const RequestDetailPage = lazyWithRetry(() =>
  import('@/pages/RequestDetailPage').then((m) => ({ default: m.RequestDetailPage })),
);
const PlatformAdminDashboard = lazyWithRetry(() => import('@/pages/PlatformAdminDashboard'));
const DealsPage = lazyWithRetry(() => import('@/pages/DealsPage'));
const QuotesPage = lazyWithRetry(() => import('@/pages/QuotesPage'));
const CategoriesPage = lazyWithRetry(() => import('@/pages/CategoriesPage'));
const EquipmentGroupsPage = lazyWithRetry(() => import('@/pages/EquipmentGroupsPage'));
const HelpPage = lazyWithRetry(() => import('@/pages/HelpPage'));
const MyRequestsPage = lazyWithRetry(() => import('@/pages/MyRequestsPage'));
const AdminUsersPage = lazyWithRetry(() => import('@/pages/AdminUsersPage'));
const AdminKYCPage = lazyWithRetry(() => import('@/pages/AdminKYCPage'));
const AdminSubscriptionsPage = lazyWithRetry(() => import('@/pages/AdminSubscriptionsPage'));
const AdminEntitlementsPage = lazyWithRetry(() => import('@/pages/AdminEntitlementsPage'));
const AdminRoleApplicationsPage = lazyWithRetry(() => import('@/pages/AdminRoleApplicationsPage'));
const AdminLeadsPage = lazyWithRetry(() => import('@/pages/AdminLeadsPage'));
const AdminCatalogPage = lazyWithRetry(() => import('@/pages/AdminCatalogPage'));
const AdminCategoriesPage = lazyWithRetry(() => import('@/pages/AdminCategoriesPage'));
const AdminEquipmentGroupsPage = lazyWithRetry(() => import('@/pages/AdminEquipmentGroupsPage'));
const AdminOffersPage = lazyWithRetry(() => import('@/pages/AdminOffersPage'));
const AdminCompaniesPage = lazyWithRetry(() => import('@/pages/AdminCompaniesPage'));
const AdminDealsPage = lazyWithRetry(() => import('@/pages/AdminDealsPage'));
const AdminMasterDataPage = lazyWithRetry(() => import('@/pages/AdminMasterDataPage'));
const AdminEmailTemplatesPage = lazyWithRetry(() => import('@/pages/AdminEmailTemplatesPage'));
const AdminOperatorRolesPage = lazyWithRetry(() => import('@/pages/AdminOperatorRolesPage'));
const AdminAccessLogPage = lazyWithRetry(() => import('@/pages/AdminAccessLogPage'));
const AdminSupportPage = lazyWithRetry(() => import('@/pages/AdminSupportPage'));
const ContractsPage = lazyWithRetry(() => import('@/pages/ContractsPage'));
const InvoicesPage = lazyWithRetry(() => import('@/pages/InvoicesPage'));
const PaymentsPage = lazyWithRetry(() => import('@/pages/PaymentsPage'));
const ActsPage = lazyWithRetry(() => import('@/pages/ActsPage'));
const OtherDocumentsPage = lazyWithRetry(() => import('@/pages/OtherDocumentsPage'));
const CompanyFilesPage = lazyWithRetry(() => import('@/pages/CompanyFilesPage'));
const FulfillmentsPage = lazyWithRetry(() => import('@/pages/FulfillmentsPage'));
const MySubscriptionPage = lazyWithRetry(() => import('@/pages/MySubscriptionPage'));
const CatalogImportPage = lazyWithRetry(() => import('@/pages/CatalogImportPage'));
const DealQuotePage = lazyWithRetry(() => import('@/pages/DealQuotePage'));
const CounterpartiesPage = lazyWithRetry(() => import('@/pages/CounterpartiesPage'));

/** Маршруты, рендерящие компонент без пропсов — таблицей, а не веткой switch. */
const PLAIN_PAGES: Record<string, ComponentType> = {
  settings: SettingsPage,
  'crm-deals': DealsPage,
  'crm-quotes': QuotesPage,
  categories: CategoriesPage,
  'equipment-groups': EquipmentGroupsPage,
  help: HelpPage,
  'my-requests': MyRequestsPage,
  'admin-users': AdminUsersPage,
  'admin-kyc': AdminKYCPage,
  'admin-subscriptions': AdminSubscriptionsPage,
  'admin-entitlements': AdminEntitlementsPage,
  'admin-role-apps': AdminRoleApplicationsPage,
  'admin-catalog': AdminCatalogPage,
  'admin-categories': AdminCategoriesPage,
  'admin-equipment-groups': AdminEquipmentGroupsPage,
  'admin-offers': AdminOffersPage,
  'admin-companies': AdminCompaniesPage,
  'admin-deals': AdminDealsPage,
  'admin-master-data': AdminMasterDataPage,
  'admin-email-templates': AdminEmailTemplatesPage,
  'admin-operator-roles': AdminOperatorRolesPage,
  'admin-access-log': AdminAccessLogPage,
  'admin-support': AdminSupportPage,
  'admin-leads': AdminLeadsPage,
  contracts: ContractsPage,
  invoices: InvoicesPage,
  payments: PaymentsPage,
  acts: ActsPage,
  'other-documents': OtherDocumentsPage,
  'company-files': CompanyFilesPage,
  fulfillments: FulfillmentsPage,
  'my-subscription': MySubscriptionPage,
  'catalog-import': CatalogImportPage,
};

export interface PageRenderContext {
  page: Page;
  role: string;
  activeStatus: CompanyStatus;
  navigateTo: (page: Page) => void;
  onNavigate: (target: string) => void;
  onProductClick: (productId: string) => void;
}

/** `activePage` шелла: обычно сам маршрут, но у нескольких страниц подсвечивается родитель. */
function activePageIdFor(page: Page, activeStatus: CompanyStatus): string {
  switch (page.type) {
    case 'product_detail':
      return 'products';
    case 'profile':
      return 'settings';
    case 'request-detail':
      return activeStatus === 'SELLER' ? 'crm-deals' : 'my-requests';
    case 'sourcing-requests':
    case 'deal-quote':
      return 'crm-deals';
    default:
      return page.type;
  }
}

/**
 * Дашборд, корректный для роли: оператору НИКОГДА не показываем покупательский дашборд —
 * именно это делал бы «сырой» default в switch.
 */
function renderDashboard(ctx: PageRenderContext): ReactNode {
  return ctx.role === 'ADMIN' ? (
    <PlatformAdminDashboard onNavigate={ctx.onNavigate} />
  ) : (
    <Dashboard onProductClick={ctx.onProductClick} onNavigate={ctx.onNavigate} />
  );
}

function renderContent(ctx: PageRenderContext): ReactNode {
  const { page, activeStatus, navigateTo, onNavigate, onProductClick } = ctx;

  const plain = PLAIN_PAGES[page.type];
  if (plain) {
    const Component = plain;
    return <Component />;
  }

  switch (page.type) {
    case 'dashboard':
      return renderDashboard(ctx);
    case 'products':
      return <ProductManagement onProductClick={onProductClick} />;
    // «Номенклатура» продавца — рабочее место, а не витрина: очередь кандидатов из заявок,
    // готовность карточки и публикация владельцем (волна A, spec-nomenclature-lifecycle).
    case 'nomenclature':
      return <NomenclatureQueuePage onProductClick={onProductClick} onNavigate={ctx.onNavigate} />;
    // T3: справочник ТН ВЭД — дерево + поиск + ИИ-режим (WCO/tarif-паттерн).
    case 'hs-directory':
      return <HSDirectoryPage />;
    case 'product_detail':
      return (
        <ProductDetail
          productId={page.productId}
          onBack={() => navigateTo({ type: 'products' })}
          onNavigate={(id) => navigateTo({ type: 'product_detail', productId: id })}
        />
      );
    case 'profile':
      // Транзитный кадр до срабатывания алиас-эффекта (#profile → #settings?section=profile) —
      // рендерим сразу Settings Hub без мигания.
      return <SettingsPage />;
    case 'request-detail':
      return (
        <RequestDetailPage
          dealId={page.dealId}
          onBack={() => navigateTo({ type: activeStatus === 'SELLER' ? 'crm-deals' : 'my-requests' })}
        />
      );
    case 'sourcing-requests':
      // Слито в единый CRM-конвейер «Сделки». Старый хэш продолжает работать, рендеря
      // каноническую поверхность (отдельной страницы нет).
      return <DealsPage />;
    case 'deal-quote':
      // Та же поверхность доступа, что и crm-deals (продавец работает над КП). Бэкенд
      // сам ограничивает запись на эндпоинтах quote/quote-item.
      return (
        <DealQuotePage
          dealId={page.dealId}
          onBack={() => navigateTo({ type: 'request-detail', dealId: page.dealId })}
          onNavigate={onNavigate}
        />
      );
    case 'clients':
      return <CounterpartiesPage direction="CLIENT" />;
    case 'suppliers':
      return <CounterpartiesPage direction="SUPPLIER" />;
    default:
      // Неизвестный/устаревший хэш → откат на дашборд, корректный для роли.
      return renderDashboard(ctx);
  }
}

export function renderPage(ctx: PageRenderContext): { content: ReactNode; activePageId: string } {
  return {
    content: renderContent(ctx),
    // Неизвестный/устаревший хэш рендерит дашборд — подсветка в шелле должна это отражать.
    // «Известность» берётся из реестра, а не из отдельного списка: иначе он стал бы пятым
    // параллельным перечнем — ровно тем, что этот рефактор устраняет.
    activePageId: KNOWN_PAGE_IDS.has(ctx.page.type) ? activePageIdFor(ctx.page, ctx.activeStatus) : 'dashboard',
  };
}
