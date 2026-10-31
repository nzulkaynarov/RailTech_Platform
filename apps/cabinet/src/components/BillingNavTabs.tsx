import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ClipboardCheck, FileSignature, Receipt } from 'lucide-react';

import { cn } from '@/lib/utils';

/** Разделы полосы: договоры, счета, акты. Экран раздела вне полосы (поставки, документы) её не показывает. */
const BILLING_SECTIONS = ['/contracts', '/invoices', '/acts'] as const;

/**
 * Полоса финансовых разделов (CAB-FIX-3, K13): навигация ссылками — `nav` и `aria-current="page"` у текущего раздела,
 * а не `role=tablist` без панелей. Только на «Договорах», «Счетах» и «Актах»: у «Документов» свой фильтр по виду, вторая
 * полоса с теми же словами дублировала бы его. На узком экране полоса прокручивается вбок целиком, ни одна подпись
 * не обрезается.
 */
export function BillingNavTabs() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  if (!BILLING_SECTIONS.some((section) => section === pathname)) return null;

  const tabs = [
    { to: '/contracts', label: t('nav.contracts'), icon: FileSignature },
    { to: '/invoices', label: t('nav.invoices'), icon: Receipt },
    { to: '/acts', label: t('nav.acts'), icon: ClipboardCheck },
  ];

  return (
    <nav aria-label={t('nav.billingTabs')} className="-mx-4 mb-4 overflow-x-auto px-4 md:mx-0 md:px-0">
      <ul className="flex w-max items-center gap-1 rounded-xl border border-border/60 bg-muted p-1 text-xs">
        {tabs.map((tab) => {
          const current = pathname === tab.to;
          return (
            <li key={tab.to} className="shrink-0">
              <Link
                to={tab.to}
                aria-current={current ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium whitespace-nowrap outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring',
                  current ? 'bg-background font-semibold text-primary shadow-xs' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <tab.icon className="size-3.5" aria-hidden="true" />
                <span>{tab.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
