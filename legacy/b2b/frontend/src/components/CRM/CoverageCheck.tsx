import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info, Loader2, ShieldCheck, Sparkles, PackageX, Repeat, FileWarning } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import type { QuoteDiffFinding, QuoteDiffIssueType, QuoteItem } from '@/api/crmApi';

/**
 * AI #3 — «КП vs заявка» coverage / discrepancy check (advisory).
 *
 * When a buyer has received a КП on their request, this surfaces a plain-language
 * summary of how the КП diverges from what was requested: uncovered (unpriced)
 * lines, non-equivalent substitutions, and notes/requirements the КП may have
 * ignored. The deterministic coverage facts come from code; the semantic verdicts
 * come from AI (only when enabled). Purely ASSISTIVE — it never blocks approving
 * or rejecting the КП.
 *
 * The parent owns the mutation (useQuoteRequestDiff) and passes the КП items so we
 * can resolve each finding's `line` index back to the requested / quoted name.
 * All text via t(); colors via semantic tokens only.
 */

// issue_type → semantic accent + icon. Compared by CODE (Rule 2), never by text.
const ISSUE_STYLE: Record<
  QuoteDiffIssueType,
  { accent: string; iconColor: string; Icon: typeof AlertTriangle; labelKey: string }
> = {
  uncovered: {
    accent: 'border-warning/20 bg-warning/10',
    iconColor: 'text-warning',
    Icon: PackageX,
    labelKey: 'coverageCheck.issue.uncovered',
  },
  substituted: {
    accent: 'border-info/20 bg-info/10',
    iconColor: 'text-info',
    Icon: Repeat,
    labelKey: 'coverageCheck.issue.substituted',
  },
  note_ignored: {
    accent: 'border-warning/20 bg-warning/10',
    iconColor: 'text-warning',
    Icon: FileWarning,
    labelKey: 'coverageCheck.issue.note_ignored',
  },
  qty_unit: {
    accent: 'border-info/20 bg-info/10',
    iconColor: 'text-info',
    Icon: Info,
    labelKey: 'coverageCheck.issue.qty_unit',
  },
};

export function CoverageCheck({
  items,
  findings,
  aiEnabled,
  isPending,
  hasRun,
  onCheck,
}: {
  items: QuoteItem[];
  findings: QuoteDiffFinding[];
  aiEnabled: boolean;
  isPending: boolean;
  hasRun: boolean;
  onCheck: () => void;
}) {
  const { t } = useTranslation();

  // Resolve a finding's `line` index back to the requested line name for context.
  const lineLabel = (index: number) => {
    const item = items[index];
    const requested = (item?.imported_raw_name ?? '').trim();
    const quoted = (item?.product_name ?? '').trim();
    return requested || quoted || t('coverageCheck.unnamedLine', { index: index + 1 });
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
              {t('coverageCheck.title')}
            </CardTitle>
            <CardDescription>{t('coverageCheck.subtitle')}</CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={onCheck}
            disabled={isPending || items.length === 0}
          >
            {isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="h-4 w-4" aria-hidden="true" />
            )}
            {t('coverageCheck.checkButton')}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {!hasRun ? (
          <p className="text-sm text-muted-foreground">{t('coverageCheck.idleHint')}</p>
        ) : findings.length === 0 ? (
          <div className="flex items-center gap-2 rounded-lg border border-success/20 bg-success/10 px-3 py-2 text-sm text-success">
            <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{t('coverageCheck.allClear')}</span>
          </div>
        ) : (
          <ul className="space-y-2">
            {findings.map((finding, position) => {
              const style = ISSUE_STYLE[finding.issue_type] ?? ISSUE_STYLE.qty_unit;
              const Icon = style.Icon;
              return (
                <li
                  key={`${finding.line}-${finding.issue_type}-${position}`}
                  className={`flex gap-2.5 rounded-lg border px-3 py-2 ${style.accent}`}
                >
                  <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${style.iconColor}`} aria-hidden="true" />
                  <div className="min-w-0 space-y-0.5">
                    <p className="text-xs font-medium text-muted-foreground">
                      {t('coverageCheck.lineLabel', { index: finding.line + 1, name: lineLabel(finding.line) })}
                    </p>
                    <p className="text-sm font-medium text-foreground">{t(style.labelKey)}</p>
                    {finding.explanation && (
                      <p className="text-sm text-muted-foreground">{finding.explanation}</p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {/* When AI is off, the deterministic coverage facts still show — make the
            degraded mode explicit so the buyer knows the semantic checks were skipped. */}
        {hasRun && !aiEnabled && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {t('coverageCheck.aiOffHint')}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default CoverageCheck;
