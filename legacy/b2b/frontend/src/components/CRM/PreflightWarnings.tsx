import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info, Loader2, ShieldCheck, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import type { PreflightFinding, PreflightLine } from '@/api/crmApi';

/**
 * AI #7 — advisory pre-flight quality warnings for a DRAFT buyer request.
 *
 * Purely advisory: the buyer presses "Check request", the component shows any
 * quality findings (vague name, missing qty/unit, likely duplicate, missing key
 * spec) inline with a suggestion each — but NEVER blocks submitting the RFQ.
 * Severity drives the color via semantic tokens (warning / info), never raw hex.
 * All text via t(); the parent owns the mutation (usePreflightCheck).
 */
export function PreflightWarnings({
  lines,
  findings,
  isPending,
  hasRun,
  onCheck,
}: {
  lines: PreflightLine[];
  findings: PreflightFinding[];
  isPending: boolean;
  hasRun: boolean;
  onCheck: () => void;
}) {
  const { t } = useTranslation();

  // Resolve each finding's line_index back to the request line for context.
  const lineLabel = (index: number) => {
    const line = lines[index];
    const name = (line?.name ?? '').trim();
    return name || t('preflight.unnamedLine', { index: index + 1 });
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
              {t('preflight.title')}
            </CardTitle>
            <CardDescription>{t('preflight.subtitle')}</CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={onCheck}
            disabled={isPending || lines.length === 0}
          >
            {isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="h-4 w-4" aria-hidden="true" />
            )}
            {t('preflight.checkButton')}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {!hasRun ? (
          <p className="text-sm text-muted-foreground">{t('preflight.idleHint')}</p>
        ) : findings.length === 0 ? (
          <div className="flex items-center gap-2 rounded-lg border border-success/20 bg-success/10 px-3 py-2 text-sm text-success">
            <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{t('preflight.allClear')}</span>
          </div>
        ) : (
          <ul className="space-y-2">
            {findings.map((finding, position) => {
              const isWarning = finding.severity === 'warning';
              const accent = isWarning
                ? 'border-warning/20 bg-warning/10'
                : 'border-info/20 bg-info/10';
              const iconColor = isWarning ? 'text-warning' : 'text-info';
              return (
                <li
                  key={`${finding.line_index}-${position}`}
                  className={`flex gap-2.5 rounded-lg border px-3 py-2 ${accent}`}
                >
                  {isWarning ? (
                    <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${iconColor}`} aria-hidden="true" />
                  ) : (
                    <Info className={`mt-0.5 h-4 w-4 shrink-0 ${iconColor}`} aria-hidden="true" />
                  )}
                  <div className="min-w-0 space-y-0.5">
                    <p className="text-xs font-medium text-muted-foreground">
                      {t('preflight.lineLabel', { index: finding.line_index + 1, name: lineLabel(finding.line_index) })}
                    </p>
                    <p className="text-sm font-medium text-foreground">{finding.issue}</p>
                    {finding.suggestion && (
                      <p className="text-sm text-muted-foreground">
                        <span className="font-medium">{t('preflight.suggestionLabel')}:</span> {finding.suggestion}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default PreflightWarnings;
