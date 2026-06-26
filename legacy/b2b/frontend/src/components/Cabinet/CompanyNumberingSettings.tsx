import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Hash, Loader2, Shield } from 'lucide-react';

import { accountsApi } from '@/api/accountsApi';
import { useAuthStore } from '@/store/authStore';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

// Server-minted document numbers are race-safe, per-company and authoritative — this
// preview is illustrative ONLY (it mirrors the backend format) and never replaces the
// value the API returns when a real document is issued.
const PREVIEW_LABEL = 'КП';
const PREVIEW_SEQ = '00001';

function buildPreview(prefix: string, year: number): string {
  const clean = prefix.trim();
  if (clean) return `${clean}-${PREVIEW_LABEL}-${year}-${PREVIEW_SEQ}`;
  return `${PREVIEW_LABEL}-${year}-${PREVIEW_SEQ}`;
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
  const isOwner = user?.workspace_role === 'OWNER';
  const year = new Date().getFullYear();

  const [prefix, setPrefix] = useState('');

  const { data: settings, isLoading } = useQuery({
    queryKey: ['company-settings', companyId],
    queryFn: () => accountsApi.getCompanySettings(companyId as number),
    enabled: companyId != null && isOwner,
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

  if (!isOwner) {
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

  return (
    <div className="space-y-6">
      <div>
        <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
          <Hash className="h-5 w-5 text-primary" aria-hidden="true" />
          {t('companyNumbering.title')}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('companyNumbering.subtitle')}</p>
      </div>

      <div className="max-w-md space-y-2">
        <Label htmlFor="cn-prefix">{t('companyNumbering.prefix')}</Label>
        <Input
          id="cn-prefix"
          value={prefix}
          maxLength={16}
          onChange={(e) => setPrefix(e.target.value)}
          placeholder={t('companyNumbering.prefixPlaceholder')}
        />
        <p className="text-xs text-muted-foreground">{t('companyNumbering.prefixHelp')}</p>
      </div>

      <div className="rounded-lg border border-border bg-muted/40 p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {t('companyNumbering.previewLabel')}
        </p>
        <p className="mt-1 font-mono text-lg font-semibold text-foreground">
          {buildPreview(prefix, year)}
        </p>
      </div>

      <Button onClick={() => saveMut.mutate(prefix.trim().slice(0, 16))} disabled={saveMut.isPending}>
        {saveMut.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
        {t('common.save')}
      </Button>
    </div>
  );
}

export default CompanyNumberingSettings;
