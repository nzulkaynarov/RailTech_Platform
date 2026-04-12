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
  'my-requests': 'breadcrumbs.myRequests',
  'request-detail': 'breadcrumbs.requestDetail',
  'crm-deals': 'breadcrumbs.crmDeals',
  'crm-quotes': 'breadcrumbs.crmQuotes',
  'crm-clients': 'breadcrumbs.crmClients',
  'sourcing-requests': 'breadcrumbs.sourcingRequests',
  'sourcing-import': 'breadcrumbs.sourcingImport',
  'sourcing-match': 'breadcrumbs.sourcingMatch',
  'production-orders': 'breadcrumbs.productionOrders',
  'production-schedule': 'breadcrumbs.productionSchedule',
  analytics: 'breadcrumbs.analytics',
  categories: 'breadcrumbs.categories',
  'equipment-groups': 'breadcrumbs.equipmentGroups',
  integrations: 'breadcrumbs.integrations',
  help: 'breadcrumbs.help',
  profile: 'breadcrumbs.profile',
  settings: 'breadcrumbs.settings',
  'my-documents': 'breadcrumbs.myDocuments',
  'admin-users': 'breadcrumbs.adminUsers',
  'admin-kyc': 'breadcrumbs.adminKyc',
  'admin-subscriptions': 'breadcrumbs.adminSubscriptions',
  'admin-role-apps': 'breadcrumbs.adminRoleApps',
  logistics: 'breadcrumbs.logistics',
  'purchase-templates': 'breadcrumbs.purchaseTemplates',
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
