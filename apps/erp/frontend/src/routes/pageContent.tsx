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
import type { Page } from './hashRoute';

const KNOWN_PAGE_IDS = new Set<string>(PAGE_IDS);

const ProductDetail = lazyWithRetry(() => import('@/pages/ProductDetail').then((m) => ({ default: m.ProductDetail })));
// R2: единый реестр «Мои товары» заменил очередь «Номенклатуры»; старый хэш — алиас.
const MyProductsPage = lazyWithRetry(() =>
  import('@/pages/MyProductsPage').then((m) => ({ default: m.MyProductsPage })),
);
// R3: карточка-редактор страницей вместо шторки.
const ProductEditorPage = lazyWithRetry(() =>
  import('@/pages/product-editor').then((m) => ({ default: m.ProductEditorPage })),
);
// R6: три справочника (ТН ВЭД · категории · группы оборудования) стали ОДНОЙ страницей с
// вкладками. Старые хэши остались рабочими маршрутами и открывают свою вкладку.
const CatalogReferencePage = lazyWithRetry(() =>
  import('@/pages/CatalogReferencePage').then((m) => ({ default: m.CatalogReferencePage })),
);
const Dashboard = lazyWithRetry(() => import('@/pages/Dashboard').then((m) => ({ default: m.Dashboard })));
const SettingsPage = lazyWithRetry(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const RequestDetailPage = lazyWithRetry(() =>
  import('@/pages/RequestDetailPage').then((m) => ({ default: m.RequestDetailPage })),
);
const DealsPage = lazyWithRetry(() => import('@/pages/DealsPage'));
const QuotesPage = lazyWithRetry(() => import('@/pages/QuotesPage'));
const HelpPage = lazyWithRetry(() => import('@/pages/HelpPage'));
const ContractsPage = lazyWithRetry(() => import('@/pages/ContractsPage'));
const InvoicesPage = lazyWithRetry(() => import('@/pages/InvoicesPage'));
const PaymentsPage = lazyWithRetry(() => import('@/pages/PaymentsPage'));
const ActsPage = lazyWithRetry(() => import('@/pages/ActsPage'));
const OtherDocumentsPage = lazyWithRetry(() => import('@/pages/OtherDocumentsPage'));
const CompanyFilesPage = lazyWithRetry(() => import('@/pages/CompanyFilesPage'));
const FulfillmentsPage = lazyWithRetry(() => import('@/pages/FulfillmentsPage'));
const CatalogImportPage = lazyWithRetry(() => import('@/pages/CatalogImportPage'));
const DealQuotePage = lazyWithRetry(() => import('@/pages/DealQuotePage'));
const CounterpartiesPage = lazyWithRetry(() => import('@/pages/CounterpartiesPage'));

/** Маршруты, рендерящие компонент без пропсов — таблицей, а не веткой switch. */
const PLAIN_PAGES: Record<string, ComponentType> = {
  settings: SettingsPage,
  'crm-deals': DealsPage,
  'crm-quotes': QuotesPage,
  help: HelpPage,
  contracts: ContractsPage,
  invoices: InvoicesPage,
  payments: PaymentsPage,
  acts: ActsPage,
  'other-documents': OtherDocumentsPage,
  'company-files': CompanyFilesPage,
  fulfillments: FulfillmentsPage,
  'catalog-import': CatalogImportPage,
};

export interface PageRenderContext {
  page: Page;
  navigateTo: (page: Page) => void;
  onNavigate: (target: string) => void;
  onProductClick: (productId: string) => void;
}

/** `activePage` шелла: обычно сам маршрут, но у нескольких страниц подсвечивается родитель. */
function activePageIdFor(page: Page): string {
  switch (page.type) {
    case 'product_detail':
    case 'products':
    case 'nomenclature':
    case 'product-new':
    case 'product-edit':
      return 'my-products';
    case 'profile':
      return 'settings';
    case 'request-detail':
    case 'sourcing-requests':
    case 'deal-quote':
      return 'crm-deals';
    // Старые маршруты справочников подсвечивают единый пункт меню — иначе переход по
    // закладке `#categories` не подсвечивал бы ничего (пункта с таким id в меню больше нет).
    case 'hs-directory':
    case 'categories':
    case 'equipment-groups':
      return 'catalog-reference';
    default:
      return page.type;
  }
}

/** Дашборд — и для неизвестного/устаревшего хэша (default в switch). */
function renderDashboard(ctx: PageRenderContext): ReactNode {
  return <Dashboard onNavigate={ctx.onNavigate} />;
}

function renderContent(ctx: PageRenderContext): ReactNode {
  const { page, navigateTo, onProductClick } = ctx;

  const plain = PLAIN_PAGES[page.type];
  if (plain) {
    const Component = plain;
    return <Component />;
  }

  switch (page.type) {
    case 'dashboard':
      return renderDashboard(ctx);
    // «Мои товары» — рабочее место бэк-офиса, а не витрина: очередь кандидатов из заявок,
    // готовность карточки и публикация владельцем (волна A, spec-nomenclature-lifecycle).
    // `products` — бывшая витрина каталога покупателя (удалена в M1-ERP-02 волна 3: витрина
    // клиента живёт в Cabinet), `nomenclature` — старая очередь; оба хэша — алиасы.
    case 'products':
    case 'nomenclature':
    case 'my-products':
      return <MyProductsPage onProductClick={onProductClick} onNavigate={ctx.onNavigate} />;
    case 'product-new':
      return <ProductEditorPage onNavigate={ctx.onNavigate} />;
    case 'product-edit':
      return <ProductEditorPage productId={page.productId} onNavigate={ctx.onNavigate} />;
    // Справочники платформы одной страницей (R6). Старые маршруты — алиасы на свою вкладку:
    // их печатают закладки, письма и уведомления, и ломать их нельзя.
    case 'catalog-reference':
      return <CatalogReferencePage />;
    case 'hs-directory':
      return <CatalogReferencePage defaultTab="hs" />;
    case 'categories':
      return <CatalogReferencePage defaultTab="categories" />;
    case 'equipment-groups':
      return <CatalogReferencePage defaultTab="groups" />;
    case 'product_detail':
      return (
        <ProductDetail
          productId={page.productId}
          onBack={() => navigateTo({ type: 'my-products' })}
          onNavigate={(id) => navigateTo({ type: 'product_detail', productId: id })}
          onProductEdit={(id) => navigateTo({ type: 'product-edit', productId: id })}
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
          onBack={() => navigateTo({ type: 'crm-deals' })}
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
        />
      );
    case 'clients':
      return <CounterpartiesPage />;
    default:
      // Неизвестный/устаревший хэш → откат на дашборд.
      return renderDashboard(ctx);
  }
}

export function renderPage(ctx: PageRenderContext): { content: ReactNode; activePageId: string } {
  return {
    content: renderContent(ctx),
    // Неизвестный/устаревший хэш рендерит дашборд — подсветка в шелле должна это отражать.
    // «Известность» берётся из реестра, а не из отдельного списка: иначе он стал бы пятым
    // параллельным перечнем — ровно тем, что этот рефактор устраняет.
    activePageId: KNOWN_PAGE_IDS.has(ctx.page.type) ? activePageIdFor(ctx.page) : 'dashboard',
  };
}
