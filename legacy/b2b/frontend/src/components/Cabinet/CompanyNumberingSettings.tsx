import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Hash, Loader2, Shield } from 'lucide-react';

import { accountsApi } from '@/api/accountsApi';
import { useAuthStore } from '@/store/authStore';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

// Server-minted document numbers are race-safe, per-company and authoritative — this
// preview is illustrative ONLY (it mirrors the backend format) and never replaces the
// value the API returns when a real document is issued.
//
// P6: the prefix brands ALL document numbers, not just КП — so preview several kinds.
// `code` is the fixed backend number-format label (see crm/services: КП/CT/INV in
// next_document_number), NOT UI text; `labelKey` is the translated «what kind» caption.
const PREVIEW_SEQ = '00001';
const PREVIEW_TYPES: { labelKey: string; code: string }[] = [
  { labelKey: 'companyNumbering.types.quote', code: 'КП' },
  { labelKey: 'companyNumbering.types.contract', code: 'CT' },
  { labelKey: 'companyNumbering.types.invoice', code: 'INV' },
];

function buildPreview(prefix: string, code: string, year: number): string {
  const clean = prefix.trim();
  if (clean) return `${clean}-${code}-${year}-${PREVIEW_SEQ}`;
  return `${code}-${year}-${PREVIEW_SEQ}`;
}

/**
 * Company-Admin (OWNER) org-admin zone: the document-numbering prefix that brands the
 * company's КП / contracts / invoices. With prefix "ACME" a number reads
 * «ACME-КП-2026-00001»; empty = the shared platform numbering «КП-2026-00001».
 * The actual number is server-minted (race-safe, gap-free) — this is a live preview only.
 */
export function CompanyNumberingSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);

  const companyId = user?.company?.id ?? user?.primary_company?.id ?? null;
  const canEditSettings = useHasCompanyPermission('settings.edit');
  const year = new Date().getFullYear();

  const [prefix, setPrefix] = useState('');

  const { data: settings, isLoading } = useQuery({
    queryKey: ['company-settings', companyId],
    queryFn: () => accountsApi.getCompanySettings(companyId as number),
    enabled: companyId != null && canEditSettings,
  });

  useEffect(() => {
    if (settings) setPrefix(settings.doc_number_prefix ?? '');
  }, [settings]);

  const saveMut = useMutation({
    mutationFn: (value: string) =>
      accountsApi.updateCompanySettings(companyId as number, { doc_number_prefix: value }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['company-settings', companyId], updated);
      toast.success(t('companyNumbering.saved'));
    },
    onError: () => toast.error(t('common.error')),
  });

  if (!canEditSettings) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4">
        <Shield className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm font-medium text-muted-foreground">{t('companyNumbering.ownerOnly')}</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex p-10 justify-center" role="status">
        <Loader2 className="h-8 w-8 text-muted-foreground animate-spin" aria-hidden="true" />
        <span className="sr-only">{t('common.loading')}</span>
      </div>
    );
  }

  // §2.4 reading-form pattern: section header left, form card right with a width cap.
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[240px_1fr]">
      <div>
        <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
          <Hash className="h-5 w-5 text-primary" aria-hidden="true" />
          {t('companyNumbering.title')}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('companyNumbering.subtitle')}</p>
      </div>

      <Card className="min-w-0 max-w-2xl">
        <CardContent className="space-y-6">
          <div className="max-w-md space-y-2">
            <Label htmlFor="cn-prefix">{t('companyNumbering.prefix')}</Label>
            <Input
              id="cn-prefix"
              value={prefix}
              maxLength={16}
              onChange={(e) => setPrefix(e.target.value.replace(/[^A-Za-z0-9_-]/g, ''))}
              placeholder={t('companyNumbering.prefixPlaceholder')}
            />
            <p className="text-xs text-muted-foreground">{t('companyNumbering.prefixHelp')}</p>
          </div>

          <div className="rounded-lg border border-border bg-muted/40 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t('companyNumbering.previewLabel')}
            </p>
            <div className="mt-2 space-y-1.5">
              {PREVIEW_TYPES.map((type) => (
                <div key={type.code} className="flex items-baseline gap-2">
                  <span className="w-24 shrink-0 text-xs text-muted-foreground">{t(type.labelKey)}</span>
                  <span className="font-mono text-base font-semibold text-foreground">
                    {buildPreview(prefix, type.code, year)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </CardContent>

        <CardFooter>
          <Button onClick={() => saveMut.mutate(prefix.trim().slice(0, 16))} disabled={saveMut.isPending}>
            {saveMut.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            {t('common.save')}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

export default CompanyNumberingSettings;
