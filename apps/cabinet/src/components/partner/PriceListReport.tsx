import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';

import type { PriceListReport, PriceListRowIssue } from '@/api/portal';
import { fieldLabelKey, issueKey } from '@/lib/partnerProducts';
import i18n from '@/i18n';

/** Отчёт о загрузке по строкам: итог плитками, затем «что исправить» — номер строки, поле, текст; замечания и предложения. */
export function PriceListReportView({ report, final }: { report: PriceListReport; final: boolean }) {
  const { t } = useTranslation();
  const tiles: Array<{ key: string; label: string; value: number; tone?: 'danger' }> = [
    { key: 'created', label: t('partner.wizard.summary.created'), value: report.created },
    { key: 'updated', label: t('partner.wizard.summary.updated'), value: report.updated },
    { key: 'offers', label: t('partner.wizard.summary.offers'), value: report.offers_created + report.offers_updated },
    { key: 'proposals', label: t('partner.wizard.summary.proposals'), value: report.proposal_count },
    { key: 'errors', label: t('partner.wizard.summary.errors'), value: report.error_count, tone: 'danger' },
  ];
  return (
    <div className="flex flex-col gap-4">
      <dl aria-label={t('partner.wizard.summaryLabel')} className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {tiles.map((tile) => (
          <div key={tile.key} className="rounded-lg border bg-card p-3">
            <dt className="text-xs text-muted-foreground">{tile.label}</dt>
            <dd className={tile.tone === 'danger' && tile.value > 0 ? 'text-xl font-semibold text-destructive' : 'text-xl font-semibold'}>
              {tile.value}
            </dd>
          </div>
        ))}
      </dl>

      {report.rows_truncated > 0 ? (
        <p role="note" className="flex items-start gap-2 text-sm text-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {t('partner.wizard.truncated', { count: report.rows_truncated })}
        </p>
      ) : null}

      {report.error_count > 0 ? (
        <IssuesTable
          title={t('partner.wizard.rowsTitle')}
          issues={report.errors}
          total={report.error_count}
          icon={<AlertTriangle className="size-4 text-destructive" aria-hidden="true" />}
        />
      ) : final ? null : (
        <p className="flex items-center gap-2 text-sm text-success">
          <CheckCircle2 className="size-4" aria-hidden="true" />
          {t('partner.wizard.previewReady')}
        </p>
      )}

      {report.warning_count > 0 ? (
        <IssuesTable
          title={t('partner.wizard.warningsTitle')}
          issues={report.warnings}
          total={report.warning_count}
          icon={<Info className="size-4 text-warning" aria-hidden="true" />}
        />
      ) : null}

      {report.proposal_count > 0 ? (
        <section aria-labelledby="proposals-title" className="flex flex-col gap-1 text-sm">
          <h3 id="proposals-title" className="font-semibold">
            {t('partner.wizard.proposalsTitle')}
          </h3>
          <p className="text-muted-foreground">{t('partner.wizard.proposalsText')}</p>
          <p>{[...new Set(report.proposals.map((proposal) => t(fieldLabelKey(proposal.field))))].join(', ')}</p>
        </section>
      ) : null}

      {report.unpublishable > 0 ? (
        <section className="flex flex-col gap-1 rounded-lg border border-info/30 bg-info/10 p-3 text-sm">
          <p className="font-medium">{t('partner.wizard.unpublishable', { count: report.unpublishable })}</p>
          {report.missing_breakdown.length > 0 ? (
            <p className="text-muted-foreground">
              {t('partner.wizard.unpublishableHint', {
                list: report.missing_breakdown.map((item) => `${t(fieldLabelKey(item.code))} (${item.count})`).join(', '),
              })}
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function IssuesTable({ title, issues, total, icon }: { title: string; issues: PriceListRowIssue[]; total: number; icon: React.ReactNode }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        {icon}
        {title}
      </h3>
      {/* Номер строки, поле и что исправить — карточкой на любой ширине: таблица в узком листе уезжала бы вбок */}
      <ul aria-label={title} className="flex flex-col divide-y rounded-lg border bg-card">
        {issues.map((issue) => (
          <li key={`${issue.row}-${issue.code}-${issue.value ?? ''}`} className="flex flex-col gap-0.5 px-3 py-2 text-sm">
            <p className="font-medium">
              {t('partner.wizard.rowHeader')} {issue.row}
              {issue.field ? <span className="font-normal text-muted-foreground"> · {t(fieldLabelKey(issue.field))}</span> : null}
            </p>
            <p className="break-words">{t(issueKey(issue, (key) => i18n.exists(key)), { value: issue.value ?? '' })}</p>
          </li>
        ))}
      </ul>
      {total > issues.length ? (
        <p className="text-xs text-muted-foreground">{t('partner.wizard.rowsShown', { shown: issues.length, total })}</p>
      ) : null}
    </section>
  );
}
