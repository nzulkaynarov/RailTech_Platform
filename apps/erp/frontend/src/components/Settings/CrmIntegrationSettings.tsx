/**
 * «Интеграция с CRM» (M3-ERP-05, ORCHESTRATOR §3.13): сопряжение одним кодом. Администратор выпускает здесь
 * одноразовый код и вводит его в CRM («Подключения → ERP → Подключить ERP») — ключи шва CRM создаёт и передаёт сама.
 * Экран — только чтение статуса + выпуск кода: значения ключей нигде не показываются, только последние 4 символа.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Check, Copy, ExternalLink, KeyRound, Link2, RefreshCw } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useCrmPairingStatus, useIssuePairingCode } from '@/hooks/useCrmPairing';
import { formatDateTime } from '@/lib/formatLocale';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 py-2 sm:grid-cols-[14rem_1fr] sm:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{children}</dd>
    </div>
  );
}

export function CrmIntegrationSettings() {
  const { t } = useTranslation();
  const { data, isLoading, isError, refetch, isFetching } = useCrmPairingStatus();
  const issue = useIssuePairingCode();
  const [copied, setCopied] = useState(false);
  const issued = issue.data;

  const crmUrl = data?.crm_frontend_url
    ? `${data.crm_frontend_url.replace(/\/+$/, '')}/integrations?tab=erp`
    : null;

  const copy = async () => {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t('settings.crmIntegration.copyFailed'));
    }
  };

  const stateBadge = () => {
    if (!data) return null;
    if (data.state === 'paired') return <Badge variant="default">{t('settings.crmIntegration.state.paired')}</Badge>;
    if (data.state === 'env') return <Badge variant="secondary">{t('settings.crmIntegration.state.env')}</Badge>;
    return <Badge variant="outline">{t('settings.crmIntegration.state.none')}</Badge>;
  };

  const keyHint = (last4: string) => (last4 ? `••••${last4}` : '—');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Link2 className="h-4 w-4" />
          {t('settings.crmIntegration.title')}
        </CardTitle>
        <CardDescription>{t('settings.crmIntegration.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : isError || !data ? (
          <Alert variant="destructive">
            <AlertTitle>{t('settings.crmIntegration.loadFailed')}</AlertTitle>
            <AlertDescription>
              <Button variant="outline" size="sm" onClick={() => refetch()}>
                {t('common.retry')}
              </Button>
            </AlertDescription>
          </Alert>
        ) : (
          <>
            <dl className="divide-y divide-border rounded-lg border border-border px-4" data-testid="crm-pairing-status">
              <Row label={t('settings.crmIntegration.status')}>
                <span className="inline-flex items-center gap-2">
                  {stateBadge()}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    aria-label={t('settings.crmIntegration.refresh')}
                    onClick={() => refetch()}
                    disabled={isFetching}
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
                  </Button>
                </span>
              </Row>
              {data.state === 'paired' && data.paired_at ? (
                <Row label={t('settings.crmIntegration.pairedAt')}>{formatDateTime(data.paired_at)}</Row>
              ) : null}
              {data.rotated_at ? (
                <Row label={t('settings.crmIntegration.rotatedAt')}>{formatDateTime(data.rotated_at)}</Row>
              ) : null}
              <Row label={t('settings.crmIntegration.keys.crmToErp')}>
                {data.state === 'env' ? t('settings.crmIntegration.fromEnv') : keyHint(data.crm_to_erp_last4)}
              </Row>
              <Row label={t('settings.crmIntegration.keys.erpToCrm')}>
                {data.erp_to_crm_configured ? t('settings.crmIntegration.issued') : '—'}
              </Row>
              <Row label={t('settings.crmIntegration.keys.webhook')}>
                {data.webhook_secret_source === 'env'
                  ? t('settings.crmIntegration.fromEnv')
                  : keyHint(data.webhook_secret_last4)}
              </Row>
            </dl>

            {data.previous_token_valid_until ? (
              <Alert>
                <AlertTitle>{t('settings.crmIntegration.transitionTitle')}</AlertTitle>
                <AlertDescription>
                  {t('settings.crmIntegration.transition', { time: formatDateTime(data.previous_token_valid_until) })}
                </AlertDescription>
              </Alert>
            ) : null}

            <section className="space-y-3" aria-labelledby="crm-pairing-code-title">
              <h2 id="crm-pairing-code-title" className="text-sm font-semibold">
                {data.state === 'paired'
                  ? t('settings.crmIntegration.repairTitle')
                  : t('settings.crmIntegration.connectTitle')}
              </h2>
              <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
                <li>{t('settings.crmIntegration.steps.issue')}</li>
                <li>{t('settings.crmIntegration.steps.enter')}</li>
                <li>{t('settings.crmIntegration.steps.done')}</li>
              </ol>

              {issued ? (
                <div className="space-y-3 rounded-lg border border-border bg-muted/40 p-4" data-testid="pairing-code-box">
                  <p className="text-xs text-muted-foreground">{t('settings.crmIntegration.codeLabel')}</p>
                  <div className="flex flex-wrap items-center gap-3">
                    <code
                      className="rounded-md bg-background px-3 py-2 font-mono text-lg tracking-wider sm:text-2xl sm:tracking-widest"
                      data-testid="pairing-code"
                    >
                      {issued.code}
                    </code>
                    <Button variant="outline" size="sm" onClick={copy}>
                      {copied ? <Check className="mr-1.5 h-3.5 w-3.5" /> : <Copy className="mr-1.5 h-3.5 w-3.5" />}
                      {copied ? t('settings.crmIntegration.copied') : t('settings.crmIntegration.copy')}
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {t('settings.crmIntegration.codeHint', {
                      minutes: Math.max(1, Math.round(issued.ttl_seconds / 60)),
                      time: formatDateTime(issued.expires_at),
                    })}
                  </p>
                </div>
              ) : null}

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  onClick={() => issue.mutate(undefined, { onError: () => toast.error(t('settings.crmIntegration.issueFailed')) })}
                  disabled={issue.isPending}
                >
                  <KeyRound className="mr-1.5 h-4 w-4" />
                  {issued ? t('settings.crmIntegration.issueAgain') : t('settings.crmIntegration.issue')}
                </Button>
                {crmUrl ? (
                  <Button variant="outline" asChild>
                    <a href={crmUrl} target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="mr-1.5 h-4 w-4" />
                      {t('settings.crmIntegration.openCrm')}
                    </a>
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground" data-testid="crm-url-missing">
                    {t('settings.platform.crmUrlMissing')}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{t('settings.crmIntegration.onceHint')}</p>
            </section>
          </>
        )}
      </CardContent>
    </Card>
  );
}
