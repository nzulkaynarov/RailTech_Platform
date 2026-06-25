import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  AlertTriangle, FileSearch, Loader2, ShieldCheck, Sparkles, Upload,
} from 'lucide-react';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import { useCheckDocument } from '@/hooks/useCRM';
import type { DocCheckResult, DocMismatchCode } from '@/api/crmApi';

/**
 * AI #6 — extract a signed contract / counter-invoice PDF and reconcile it vs the
 * referenced КП (quote) or Contract.
 *
 * The buyer uploads the document; Claude TRANSCRIBES {total, currency, valid_until,
 * bank_details, line_totals} (treated as untrusted OCR) and the backend recomputes
 * the money comparison in Decimal — this component only RENDERS the verdict. Each
 * mismatch is keyed by a stable machine `code` (compared by code, not name) and
 * mapped to an i18n message. Advisory only: never blocks signing.
 *
 * Pass exactly one of quoteId / contractId (the record of truth to reconcile against).
 */
export function DocumentCheck({
  quoteId,
  contractId,
}: {
  quoteId?: number;
  contractId?: number;
}) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [result, setResult] = useState<DocCheckResult | null>(null);
  const check = useCheckDocument();

  const onPick = async (file: File) => {
    setResult(null);
    try {
      const data = await check.mutateAsync({ file, quoteId, contractId });
      setResult(data);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const comparison = result?.comparison;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
              {t('documentCheck.title')}
            </CardTitle>
            <CardDescription>{t('documentCheck.subtitle')}</CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => inputRef.current?.click()}
            disabled={check.isPending}
          >
            {check.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Upload className="h-4 w-4" aria-hidden="true" />
            )}
            {t('documentCheck.uploadButton')}
          </Button>
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            accept=".pdf,.jpg,.jpeg,.png,.webp"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onPick(file);
              e.target.value = '';
            }}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {!result ? (
          <p className="text-sm text-muted-foreground">{t('documentCheck.idleHint')}</p>
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground">{t('documentCheck.fields.total')}</dt>
                <dd className="tabular-nums font-medium text-foreground">
                  {comparison?.parsed.document_total ?? '—'}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t('documentCheck.fields.currency')}</dt>
                <dd className="font-medium text-foreground">
                  {comparison?.parsed.document_currency ?? '—'}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t('documentCheck.fields.validUntil')}</dt>
                <dd className="text-foreground">{comparison?.parsed.valid_until ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t('documentCheck.fields.lineCount')}</dt>
                <dd className="text-foreground">{comparison?.parsed.line_count ?? 0}</dd>
              </div>
              {comparison?.parsed.bank_details && (
                <div className="col-span-2">
                  <dt className="text-xs text-muted-foreground">{t('documentCheck.fields.bankDetails')}</dt>
                  <dd className="whitespace-pre-wrap text-foreground">{comparison.parsed.bank_details}</dd>
                </div>
              )}
            </dl>

            {comparison?.ok ? (
              <div className="flex items-center gap-2 rounded-lg border border-success/20 bg-success/10 px-3 py-2 text-sm text-success">
                <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{t('documentCheck.allClear')}</span>
              </div>
            ) : (
              <ul className="space-y-2">
                {comparison?.mismatches.map((mismatch, position) => (
                  <li
                    key={`${mismatch.code}-${position}`}
                    className="flex gap-2.5 rounded-lg border border-warning/20 bg-warning/10 px-3 py-2 text-sm"
                  >
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                    <div className="min-w-0 space-y-0.5">
                      <p className="font-medium text-foreground">
                        {t(`documentCheck.mismatch.${mismatch.code satisfies DocMismatchCode}`)}
                      </p>
                      {mismatch.code === 'TOTAL_MISMATCH' && (
                        <p className="text-xs text-muted-foreground">
                          {t('documentCheck.totalDetail', {
                            document: mismatch.document_total,
                            expected: mismatch.expected_total,
                            difference: mismatch.difference,
                          })}
                        </p>
                      )}
                      {mismatch.code === 'FOREIGN_CURRENCY' && (
                        <p className="text-xs text-muted-foreground">
                          {t('documentCheck.currencyDetail', {
                            document: mismatch.document_currency,
                            expected: mismatch.expected_currency,
                          })}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <FileSearch className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {t('documentCheck.advisoryNote')}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default DocumentCheck;
