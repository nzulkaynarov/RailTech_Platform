import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Copy,
  Check,
  FileText,
  Clock,
  ArrowLeft,
  FileQuestion,
} from 'lucide-react';

import { useVerifyDocument } from '@/api/queries';
import { isPortalApiError } from '@/api/portal';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { ToneBadge } from '@/components/StatusBadge';
import { FileField } from '@/components/FileField';
import { StatusScreen } from '@/components/StatusScreen';
import { usePageTitle } from '@/hooks/usePageTitle';
import { formatDate, formatDateTime } from '@/lib/format';

export function VerifyPage() {
  const { code = '' } = useParams<{ code: string }>();
  const { t } = useTranslation();
  usePageTitle(t('verify.pageTitle'));

  const query = useVerifyDocument(code);
  const [copied, setCopied] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileHashState, setFileHashState] = useState<{
    fileName: string;
    computedHash: string;
    isMatch: boolean;
  } | null>(null);
  const [isHashing, setIsHashing] = useState(false);

  const handleCopyHash = async (hash: string) => {
    try {
      await navigator.clipboard.writeText(hash);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard write failed silently
    }
  };

  const handleFileChange = async (file: File | null) => {
    setSelectedFile(file);
    if (!file) {
      setFileHashState(null);
      return;
    }
    const expectedHash = query.data?.sha256_hash;
    setIsHashing(true);
    try {
      const buffer = await file.arrayBuffer();
      const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      const hashHex = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
      const isMatch = Boolean(expectedHash && hashHex.toLowerCase() === expectedHash.toLowerCase());
      setFileHashState({
        fileName: file.name,
        computedHash: hashHex,
        isMatch,
      });
    } catch {
      setFileHashState(null);
    } finally {
      setIsHashing(false);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col bg-muted/40 text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b bg-background px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold">
            RT
          </div>
          <div>
            <p className="text-sm font-semibold leading-tight">{t('app.name')}</p>
            <p className="text-xs text-muted-foreground">{t('verify.pageTitle')}</p>
          </div>
        </div>
        <LanguageSwitcher />
      </header>

      <main id="main" className="flex flex-1 items-start justify-center px-4 py-8 sm:px-6">
        <div className="w-full max-w-2xl space-y-6">
          {query.isLoading && (
            <StatusScreen title={t('app.loading')} text={t('verify.pageTitle')} loading />
          )}

          {query.isError && (
            <Card className="border-border">
              <CardHeader className="text-center">
                {isPortalApiError(query.error, 404) ? (
                  <>
                    <div className="mx-auto mb-3 flex size-14 items-center justify-center rounded-full bg-warning/10 text-warning">
                      <FileQuestion className="size-8" />
                    </div>
                    <CardTitle className="text-xl font-bold">{t('verify.notFoundTitle')}</CardTitle>
                    <CardDescription className="text-sm">
                      {t('verify.notFoundText', { code })}
                    </CardDescription>
                  </>
                ) : isPortalApiError(query.error, 429) ? (
                  <>
                    <div className="mx-auto mb-3 flex size-14 items-center justify-center rounded-full bg-destructive/10 text-destructive">
                      <Clock className="size-8" />
                    </div>
                    <CardTitle className="text-xl font-bold">{t('verify.rateLimitedTitle')}</CardTitle>
                    <CardDescription className="text-sm">
                      {t('verify.rateLimitedText', { seconds: query.error.retryAfter ?? 60 })}
                    </CardDescription>
                  </>
                ) : (
                  <>
                    <div className="mx-auto mb-3 flex size-14 items-center justify-center rounded-full bg-destructive/10 text-destructive">
                      <AlertTriangle className="size-8" />
                    </div>
                    <CardTitle className="text-xl font-bold">{t('common.error')}</CardTitle>
                    <CardDescription className="text-sm">{query.error.message}</CardDescription>
                  </>
                )}
              </CardHeader>
              <CardContent className="flex justify-center pt-2">
                <Button asChild variant="outline">
                  <Link to="/" className="inline-flex items-center gap-2">
                    <ArrowLeft className="size-4" />
                    {t('verify.backHome')}
                  </Link>
                </Button>
              </CardContent>
            </Card>
          )}

          {query.data && (
            <>
              {/* Статус подлинности / отзыва */}
              {query.data.status === 'valid' ? (
                <div
                  data-testid="status-valid"
                  className="flex items-start gap-3.5 rounded-xl border border-success/30 bg-success/10 p-4 text-foreground"
                >
                  <ShieldCheck className="size-6 shrink-0 text-success" />
                  <div>
                    <div className="flex items-center gap-2">
                      <ToneBadge tone="success" className="font-semibold">
                        {t('verify.verifiedBadge')}
                      </ToneBadge>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {t('verify.verifiedSub')}
                    </p>
                  </div>
                </div>
              ) : (
                <div
                  data-testid="status-revoked"
                  className="flex items-start gap-3.5 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-destructive-foreground dark:border-destructive/20"
                >
                  <AlertTriangle className="size-6 shrink-0 text-destructive" />
                  <div>
                    <div className="flex items-center gap-2">
                      <ToneBadge tone="danger" className="font-semibold">
                        {t('verify.revokedBadge')}
                      </ToneBadge>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">{t('verify.revokedSub')}</p>
                    {query.data.revocation_reason && (
                      <p className="mt-2 text-sm font-medium text-destructive">
                        {t('verify.revokedReason')}: {query.data.revocation_reason}
                      </p>
                    )}
                    {query.data.revoked_at && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {t('verify.revokedAt')}: {formatDateTime(query.data.revoked_at)}
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* Карточка реквизитов */}
              <Card>
                <CardHeader className="pb-3 border-b">
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle className="text-lg font-bold">{t('verify.documentDetails')}</CardTitle>
                      <CardDescription>
                        {t(`verify.kinds.${query.data.kind}`)} №{' '}
                        {query.data.number}
                      </CardDescription>
                    </div>
                    <FileText className="size-5 text-muted-foreground" />
                  </div>
                </CardHeader>
                <CardContent className="pt-4">
                  <dl className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2 text-sm">
                    <div>
                      <dt className="text-xs text-muted-foreground">{t('verify.kind')}</dt>
                      <dd className="font-medium">
                        {t(`verify.kinds.${query.data.kind}`)}
                      </dd>
                    </div>

                    <div>
                      <dt className="text-xs text-muted-foreground">{t('verify.number')}</dt>
                      <dd className="font-medium font-mono">{query.data.number}</dd>
                    </div>

                    <div>
                      <dt className="text-xs text-muted-foreground">{t('verify.date')}</dt>
                      <dd className="font-medium">{formatDate(query.data.date)}</dd>
                    </div>

                    <div>
                      <dt className="text-xs text-muted-foreground">{t('verify.company')}</dt>
                      <dd className="font-medium">{query.data.company_name}</dd>
                    </div>

                    <div>
                      <dt className="text-xs text-muted-foreground">{t('verify.signatory')}</dt>
                      <dd className="font-medium">
                        {query.data.signatory_name}
                        {query.data.signatory_position && (
                          <span className="block text-xs text-muted-foreground">
                            {query.data.signatory_position}
                          </span>
                        )}
                      </dd>
                    </div>

                    <div>
                      <dt className="text-xs text-muted-foreground">{t('verify.basis')}</dt>
                      <dd className="font-medium">{query.data.signatory_basis || '—'}</dd>
                    </div>

                    <div>
                      <dt className="text-xs text-muted-foreground">{t('verify.signedAt')}</dt>
                      <dd className="font-medium">{formatDateTime(query.data.signed_at)}</dd>
                    </div>

                    <div>
                      <dt className="text-xs text-muted-foreground">{t('verify.code')}</dt>
                      <dd className="font-mono text-xs">{query.data.code}</dd>
                    </div>

                    {query.data.sha256_hash && (
                      <div className="sm:col-span-2 rounded-lg border bg-muted/30 p-3">
                        <dt className="text-xs font-semibold text-muted-foreground">
                          {t('verify.sha256')}
                        </dt>
                        <dd className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                          <code className="text-xs font-mono break-all select-all text-foreground">
                            {query.data.sha256_hash}
                          </code>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-8 shrink-0 px-2 text-xs"
                            onClick={() => handleCopyHash(query.data.sha256_hash!)}
                          >
                            {copied ? (
                              <>
                                <Check className="mr-1 size-3 text-success" />
                                {t('verify.copied')}
                              </>
                            ) : (
                              <>
                                <Copy className="mr-1 size-3" />
                                {t('verify.copyHash')}
                              </>
                            )}
                          </Button>
                        </dd>
                      </div>
                    )}
                  </dl>
                </CardContent>
              </Card>

              {/* Проверка локального файла */}
              {query.data.sha256_hash && (
                <Card>
                  <CardHeader className="pb-3 border-b">
                    <CardTitle className="text-base font-semibold">
                      {t('verify.fileVerifyTitle')}
                    </CardTitle>
                    <CardDescription>{t('verify.fileVerifyDesc')}</CardDescription>
                  </CardHeader>
                  <CardContent className="pt-4 space-y-4">
                    <Label htmlFor="verify-file" className="sr-only">
                      {t('verify.fileVerifyTitle')}
                    </Label>
                    <FileField
                      id="verify-file"
                      value={selectedFile}
                      onChange={handleFileChange}
                      accept="application/pdf"
                    />

                    {isHashing && (
                      <p className="text-center text-sm text-muted-foreground">
                        {t('verify.calculatingHash')}
                      </p>
                    )}

                    {fileHashState && (
                      <div
                        data-testid="hash-result"
                        className={`rounded-lg border p-4 ${
                          fileHashState.isMatch
                            ? 'border-success/30 bg-success/10 text-foreground'
                            : 'border-destructive/30 bg-destructive/10 text-destructive-foreground'
                        }`}
                      >
                        <div className="flex items-start gap-2.5">
                          {fileHashState.isMatch ? (
                            <CheckCircle2 className="size-5 shrink-0 text-success" />
                          ) : (
                            <XCircle className="size-5 shrink-0 text-destructive" />
                          )}
                          <div className="space-y-1 text-sm">
                            <p className="font-semibold">
                              {fileHashState.isMatch
                                ? t('verify.hashMatch')
                                : t('verify.hashMismatch')}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {t('verify.fileHashLabel')}:{' '}
                              <code className="font-mono break-all">{fileHashState.computedHash}</code>
                            </p>
                            {!fileHashState.isMatch && (
                              <p className="text-xs text-muted-foreground">
                                {t('verify.expectedHashLabel')}:{' '}
                                <code className="font-mono break-all">{query.data.sha256_hash}</code>
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
