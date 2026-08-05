import * as React from 'react';
import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Home } from 'lucide-react';
import { TFunction } from 'i18next';

export interface BreadcrumbSegment {
  label: string;
  pageId?: string; // if clickable
}

interface PageBreadcrumbProps {
  segments: BreadcrumbSegment[];
  onNavigate: (pageId: string) => void;
}

const pageI18nKeys: Record<string, string> = {
  dashboard: 'breadcrumbs.dashboard',
  products: 'breadcrumbs.products',
  nomenclature: 'breadcrumbs.nomenclature',
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

export function PageBreadcrumb({ segments, onNavigate }: PageBreadcrumbProps) {
  if (segments.length === 0) return null;

  return (
    <Breadcrumb className="mb-4">
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink
            className="cursor-pointer flex items-center gap-1"
            onClick={() => onNavigate('dashboard')}
          >
            <Home className="h-3.5 w-3.5" />
          </BreadcrumbLink>
        </BreadcrumbItem>
        {segments.map((seg, i) => (
          <React.Fragment key={i}>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              {i < segments.length - 1 && seg.pageId ? (
                <BreadcrumbLink
                  className="cursor-pointer"
                  onClick={() => onNavigate(seg.pageId!)}
                >
                  {seg.label}
                </BreadcrumbLink>
              ) : (
                <BreadcrumbPage>{seg.label}</BreadcrumbPage>
              )}
            </BreadcrumbItem>
          </React.Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
