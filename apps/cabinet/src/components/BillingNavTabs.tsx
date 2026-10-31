import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ClipboardCheck, FileSignature, FolderOpen, Receipt } from 'lucide-react';

import { cn } from '@/lib/utils';

/** Консолидированный таб-бар для финансового и договорного контура. */
export function BillingNavTabs() {
  const { t } = useTranslation();
  const location = useLocation();

  const tabs = [
    { to: '/contracts', label: t('nav.contracts'), icon: FileSignature },
    { to: '/invoices', label: t('nav.invoices'), icon: Receipt },
    { to: '/acts', label: t('nav.acts'), icon: ClipboardCheck },
    { to: '/documents', label: t('nav.documents'), icon: FolderOpen },
  ];

  return (
    <div
      role="tablist"
      aria-label={t('nav.billingTabs')}
      className="mb-4 inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-xl border border-border/60 bg-muted p-1 text-xs"
    >
      {tabs.map((tab) => {
        const isActive = location.pathname === tab.to;
        return (
          <Link
            key={tab.to}
            to={tab.to}
            role="tab"
            aria-selected={isActive}
            className={cn(
              'flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 font-medium transition-all duration-150 ease-out outline-none focus-visible:ring-2 focus-visible:ring-ring',
              isActive
                ? 'bg-background font-semibold text-primary shadow-xs'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <tab.icon className="size-3.5" aria-hidden="true" />
            <span>{tab.label}</span>
          </Link>
        );
      })}
    </div>
  );
}
