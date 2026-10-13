/**
 * Подпись страницы по её id. Вынесено из компонента-хлебных-крошек: файл с компонентом
 * и хелпером ломает Fast Refresh (react-refresh/only-export-components).
 */

import type { TFunction } from 'i18next';

const pageI18nKeys: Record<string, string> = {
  dashboard: 'breadcrumbs.dashboard',
  products: 'breadcrumbs.products',
  // R2: «Номенклатура» стала «Мои товары»; старый id — алиас и печатает ту же крошку.
  nomenclature: 'breadcrumbs.myProducts',
  'my-products': 'breadcrumbs.myProducts',
  'product-new': 'breadcrumbs.productNew',
  'product-edit': 'breadcrumbs.productEdit',
  'hs-directory': 'breadcrumbs.hsDirectory',
  'my-requests': 'breadcrumbs.myRequests',
  'request-detail': 'breadcrumbs.requestDetail',
  'crm-deals': 'breadcrumbs.crmDeals',
  'crm-quotes': 'breadcrumbs.crmQuotes',
  'crm-clients': 'breadcrumbs.crmClients',
  'sourcing-requests': 'breadcrumbs.sourcingRequests',
  'production-orders': 'breadcrumbs.productionOrders',
  'production-schedule': 'breadcrumbs.productionSchedule',
  analytics: 'breadcrumbs.analytics',
  categories: 'breadcrumbs.categories',
  'equipment-groups': 'breadcrumbs.equipmentGroups',
  // R6: единая страница справочников. Без строки в этой таблице крошка печатала бы сырой
  // идентификатор маршрута — `getPageLabel` возвращает pageId, когда ключа нет.
  'catalog-reference': 'breadcrumbs.catalogReference',
  integrations: 'breadcrumbs.integrations',
  help: 'breadcrumbs.help',
  profile: 'breadcrumbs.profile',
  settings: 'breadcrumbs.settings',
  'my-documents': 'breadcrumbs.myDocuments',
  'admin-users': 'breadcrumbs.adminUsers',
  'admin-kyc': 'breadcrumbs.adminKyc',
  'admin-subscriptions': 'breadcrumbs.adminSubscriptions',
  'admin-entitlements': 'breadcrumbs.adminEntitlements',
  'admin-access-log': 'breadcrumbs.adminAccessLog',
  'admin-email-templates': 'breadcrumbs.adminEmailTemplates',
  'admin-role-apps': 'breadcrumbs.adminRoleApps',
  'admin-leads': 'breadcrumbs.adminLeads',
  'admin-master-data': 'breadcrumbs.adminMasterData',
  'admin-operator-roles': 'breadcrumbs.adminOperatorRoles',
  'admin-support': 'breadcrumbs.adminSupport',
  'admin-catalog': 'breadcrumbs.adminCatalog',
  'admin-categories': 'breadcrumbs.adminCategories',
  'admin-equipment-groups': 'breadcrumbs.adminEquipmentGroups',
  'admin-offers': 'breadcrumbs.adminOffers',
  'admin-companies': 'breadcrumbs.adminCompanies',
  'admin-deals': 'breadcrumbs.adminDeals',
  logistics: 'breadcrumbs.logistics',
  'purchase-templates': 'breadcrumbs.purchaseTemplates',
  // Billing children
  contracts: 'breadcrumbs.contracts',
  invoices: 'breadcrumbs.invoices',
  payments: 'breadcrumbs.payments',
  acts: 'breadcrumbs.acts',
  fulfillments: 'breadcrumbs.fulfillments',
  leads: 'breadcrumbs.leads',
  'my-subscription': 'breadcrumbs.mySubscription',
  'forgot-password': 'breadcrumbs.forgotPassword',
  'reset-password': 'breadcrumbs.resetPassword',
};

export function getPageLabel(pageId: string, t: TFunction): string {
  const key = pageI18nKeys[pageId];
  return key ? t(key) : pageId;
}
