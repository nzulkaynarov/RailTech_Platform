import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Briefcase,
  Building2,
  ClipboardCheck,
  FilePlus2,
  FileSignature,
  FileText,
  FolderOpen,
  Inbox,
  Package,
  Plus,
  Receipt,
  Truck,
  Users,
  type LucideIcon,
} from 'lucide-react';

import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { CanAct } from '@/session/CanAct';

/**
 * Экраны разделов ARCHITECTURE §5 — оболочка M2-CAB-01: заголовок и пустое состояние.
 * Данные и действия экранов — M2-CAB-02 (CLAUDE.md §4), каждый экран заменит свою заглушку.
 */
function SectionStub({
  title,
  icon,
  emptyTitle,
  emptyText,
  actions,
}: {
  title: string;
  icon: LucideIcon;
  emptyTitle: string;
  emptyText: string;
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={title} actions={actions} />
      <EmptyState icon={icon} title={emptyTitle} text={emptyText}>
        <p className="text-xs text-muted-foreground">{t('common.comingSoon')}</p>
      </EmptyState>
    </>
  );
}

export function RequestsPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.requests.title')}
      icon={Inbox}
      emptyTitle={t('pages.requests.emptyTitle')}
      emptyText={t('pages.requests.emptyText')}
      actions={
        <CanAct>
          <Button asChild>
            <Link to="/requests/new">
              <Plus aria-hidden="true" />
              {t('pages.requests.new')}
            </Link>
          </Button>
        </CanAct>
      }
    />
  );
}

export function RequestNewPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.requestNew.title')}
      icon={FilePlus2}
      emptyTitle={t('pages.requestNew.emptyTitle')}
      emptyText={t('pages.requestNew.emptyText')}
    />
  );
}

export function RequestDetailPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  return (
    <SectionStub
      title={t('pages.requestDetail.title', { id })}
      icon={Inbox}
      emptyTitle={t('pages.requestDetail.emptyTitle')}
      emptyText={t('pages.requestDetail.emptyText')}
    />
  );
}

export function QuotesPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.quotes.title')}
      icon={FileText}
      emptyTitle={t('pages.quotes.emptyTitle')}
      emptyText={t('pages.quotes.emptyText')}
    />
  );
}

export function QuoteDetailPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  return (
    <SectionStub
      title={t('pages.quoteDetail.title', { id })}
      icon={FileText}
      emptyTitle={t('pages.quoteDetail.emptyTitle')}
      emptyText={t('pages.quoteDetail.emptyText')}
    />
  );
}

export function ContractsPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.contracts.title')}
      icon={FileSignature}
      emptyTitle={t('pages.contracts.emptyTitle')}
      emptyText={t('pages.contracts.emptyText')}
    />
  );
}

export function InvoicesPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.invoices.title')}
      icon={Receipt}
      emptyTitle={t('pages.invoices.emptyTitle')}
      emptyText={t('pages.invoices.emptyText')}
    />
  );
}

export function ActsPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.acts.title')}
      icon={ClipboardCheck}
      emptyTitle={t('pages.acts.emptyTitle')}
      emptyText={t('pages.acts.emptyText')}
    />
  );
}

export function DeliveriesPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.deliveries.title')}
      icon={Truck}
      emptyTitle={t('pages.deliveries.emptyTitle')}
      emptyText={t('pages.deliveries.emptyText')}
    />
  );
}

export function DocumentsPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.documents.title')}
      icon={FolderOpen}
      emptyTitle={t('pages.documents.emptyTitle')}
      emptyText={t('pages.documents.emptyText')}
    />
  );
}

export function CatalogPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.catalog.title')}
      icon={Package}
      emptyTitle={t('pages.catalog.emptyTitle')}
      emptyText={t('pages.catalog.emptyText')}
    />
  );
}

export function CatalogItemPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  return (
    <SectionStub
      title={t('pages.catalogItem.title', { id })}
      icon={Package}
      emptyTitle={t('pages.catalogItem.emptyTitle')}
      emptyText={t('pages.catalogItem.emptyText')}
    />
  );
}

export function CompanyPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.company.title')}
      icon={Building2}
      emptyTitle={t('pages.company.emptyTitle')}
      emptyText={t('pages.company.emptyText')}
    />
  );
}

export function TeamPage() {
  const { t } = useTranslation();
  return (
    <SectionStub
      title={t('pages.team.title')}
      icon={Users}
      emptyTitle={t('pages.team.emptyTitle')}
      emptyText={t('pages.team.emptyText')}
    />
  );
}

/** Сделка — цель deep-link `start_param=deal_<id>` из бота; собирается из списков по `deal_id` (M2-CAB-02). */
export function DealPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  return (
    <SectionStub
      title={t('pages.deal.title', { id })}
      icon={Briefcase}
      emptyTitle={t('pages.deal.emptyTitle')}
      emptyText={t('pages.deal.emptyText')}
    />
  );
}
