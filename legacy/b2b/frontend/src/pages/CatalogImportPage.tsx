import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Package, Upload, FileSpreadsheet, Download, CheckCircle2, Loader2, AlertCircle, SearchCheck } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { PageShell } from './shared/PageShell';
import { sourcingApi, type CatalogImportResult } from '@/api/sourcingApi';
import { translateApiError } from '@/lib/apiError';

type TaskStatus = 'PENDING' | 'STARTED' | 'PROGRESS' | 'SUCCESS' | 'FAILURE' | 'REVOKED' | string;

/** Map a backend row-error code to a friendly message. */
function useRowErrorText() {
  const { t } = useTranslation();
  return (message: string): string => {
    if (message.startsWith('UNKNOWN_CURRENCY')) {
      return t('catalogImport.err.unknownCurrency', { code: message.split(':')[1] ?? '' });
    }
    if (message.startsWith('UNKNOWN_STOCK_STATUS')) {
      return t('catalogImport.err.unknownStock', { code: message.split(':')[1] ?? '' });
    }
    if (message === 'PRICE_NOT_A_NUMBER') return t('catalogImport.err.badPrice');
    if (message === 'ROW_FAILED') return t('catalogImport.err.rowFailed');
    return message;
  };
}

/**
 * SELLER / MANUFACTURER self-serve catalog bulk import (true-PIM). Two steps:
 * a dry-run "check" that previews counts + row errors without persisting, then
 * the real import. Posts to `/sourcing/import-catalog/` (member-gated) and polls
 * task status. The uploader's company is the supplier on every offer.
 */
export function CatalogImportPage() {
  const { t } = useTranslation();
  const rowErrorText = useRowErrorText();
  const [file, setFile] = useState<File | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [taskResult, setTaskResult] = useState<CatalogImportResult | null>(null);
  const [taskMeta, setTaskMeta] = useState<{ current?: number; total?: number } | null>(null);
  const [busy, setBusy] = useState<'check' | 'import' | null>(null);
  const [checkedOk, setCheckedOk] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Poll the Celery task status while it's running.
  useEffect(() => {
    if (!taskId) return;
    const isTerminal = (s: TaskStatus | null) => s === 'SUCCESS' || s === 'FAILURE' || s === 'REVOKED';
    if (isTerminal(taskStatus)) return;

    let cancelled = false;
    const tick = async () => {
      try {
        const data = await sourcingApi.getImportStatus(taskId);
        if (cancelled) return;
        setTaskStatus(data.status);
        setTaskMeta(data.meta ?? null);
        if (data.status === 'SUCCESS') {
          const result = data.result ?? null;
          setTaskResult(result);
          if (result?.dry_run && result?.status === 'success') setCheckedOk(true);
        }
      } catch {
        /* transient, keep trying */
      }
    };
    const interval = setInterval(tick, 2000);
    tick();
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [taskId, taskStatus]);

  function pickFile(next: File | null) {
    setFile(next);
    setCheckedOk(false);
    setTaskId(null);
    setTaskStatus(null);
    setTaskResult(null);
    setTaskMeta(null);
  }

  async function runImport(dryRun: boolean) {
    if (!file) return;
    setBusy(dryRun ? 'check' : 'import');
    setTaskId(null);
    setTaskStatus(null);
    setTaskResult(null);
    setTaskMeta(null);
    try {
      const { task_id } = await sourcingApi.importCatalog(file, dryRun);
      setTaskId(task_id);
      setTaskStatus('PENDING');
      toast.success(dryRun ? t('catalogImport.checkQueued') : t('catalogImport.queued'));
    } catch (e) {
      toast.error(translateApiError(e));
    } finally {
      setBusy(null);
    }
  }

  async function downloadTemplate() {
    try {
      const blob = await sourcingApi.downloadCatalogTemplate();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'railtech_catalog_template.xlsx';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  }

  const isTerminal = taskStatus === 'SUCCESS' || taskStatus === 'FAILURE' || taskStatus === 'REVOKED';
  const isError = taskResult?.status === 'error';
  const errors = taskResult?.errors ?? [];
  const progress =
    taskMeta?.total && taskMeta.total > 0
      ? Math.round(((taskMeta.current ?? 0) / taskMeta.total) * 100)
      : taskStatus === 'SUCCESS'
        ? 100
        : taskStatus === 'PENDING' || taskStatus === 'STARTED'
          ? 10
          : 50;

  return (
    <PageShell
      title={t('catalogImport.title')}
      description={t('catalogImport.description')}
      icon={<Package className="h-5 w-5" />}
    >
      <div className="max-w-4xl space-y-6">
        <Card>
          <CardContent className="space-y-3 p-5">
            <div className="flex items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Badge variant="outline" className="text-xs">1</Badge>
                {t('catalogImport.template')}
              </h3>
              <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={downloadTemplate}>
                <Download className="h-3.5 w-3.5" aria-hidden="true" />
                {t('catalogImport.downloadTemplate')}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">{t('catalogImport.templateHint')}</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-3 p-5">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Badge variant="outline" className="text-xs">2</Badge>
              {t('catalogImport.uploadFile')}
            </h3>
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
            />
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={() => inputRef.current?.click()}>
                <Upload className="h-4 w-4" aria-hidden="true" />
                {t('catalogImport.pickFile')}
              </Button>
              <span className="truncate text-xs text-muted-foreground">
                {file ? file.name : t('catalogImport.noFile')}
              </span>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button
                variant="outline"
                className="flex-1"
                disabled={!file || busy !== null}
                onClick={() => runImport(true)}
              >
                {busy === 'check' ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <SearchCheck className="h-4 w-4" aria-hidden="true" />
                )}
                {t('catalogImport.checkFile')}
              </Button>
              <Button
                className="flex-1"
                disabled={!file || busy !== null || !checkedOk}
                onClick={() => runImport(false)}
              >
                {busy === 'import' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                {t('catalogImport.startImport')}
              </Button>
            </div>
            {file && !checkedOk ? (
              <p className="text-xs text-muted-foreground">{t('catalogImport.checkFirstHint')}</p>
            ) : null}
          </CardContent>
        </Card>

        {taskId ? (
          <Card>
            <CardContent className="space-y-3 p-5">
              <div className="flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold">
                  <Badge variant="outline" className="text-xs">3</Badge>
                  {taskResult?.dry_run ? t('catalogImport.previewTitle') : t('catalogImport.progress')}
                </h3>
                <Badge
                  variant={
                    taskStatus === 'SUCCESS' && !isError
                      ? 'default'
                      : taskStatus === 'FAILURE' || isError
                        ? 'destructive'
                        : 'secondary'
                  }
                >
                  {taskResult?.dry_run ? t('catalogImport.dryRunBadge') : taskStatus ?? 'PENDING'}
                </Badge>
              </div>
              <Progress value={progress} className="h-2" />
              {taskMeta?.current != null && taskMeta.total ? (
                <p className="text-xs tabular-nums text-muted-foreground">
                  {taskMeta.current} / {taskMeta.total}
                </p>
              ) : null}

              {isTerminal && taskStatus === 'SUCCESS' && !isError ? (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <Stat label={t('catalogImport.stat.created')} value={taskResult?.created} />
                    <Stat label={t('catalogImport.stat.updated')} value={taskResult?.updated} />
                    <Stat label={t('catalogImport.stat.offers')} value={taskResult?.offers_upserted} />
                    <Stat label={t('catalogImport.stat.skipped')} value={taskResult?.skipped} tone="warn" />
                  </div>

                  {taskResult?.dry_run ? (
                    <div className="flex items-start gap-2 rounded-md border border-info/40 bg-info/5 p-3 text-xs">
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 text-info" aria-hidden="true" />
                      <div className="text-foreground">{t('catalogImport.previewHint')}</div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-2 rounded-md border border-success/40 bg-success/5 p-3 text-xs">
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 text-success" aria-hidden="true" />
                      <div className="font-medium text-success">{t('catalogImport.successTitle')}</div>
                    </div>
                  )}

                  {errors.length > 0 ? (
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-destructive">
                        {t('catalogImport.errorsTitle', { count: taskResult?.error_count ?? errors.length })}
                      </p>
                      <div className="max-h-48 overflow-auto rounded-md border border-border">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-20">{t('catalogImport.errRow')}</TableHead>
                              <TableHead>{t('catalogImport.errReason')}</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {errors.map((rowError) => (
                              <TableRow key={rowError.row}>
                                <TableCell className="tabular-nums text-muted-foreground">{rowError.row}</TableCell>
                                <TableCell>{rowErrorText(rowError.message)}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {(isTerminal && taskStatus !== 'SUCCESS') || isError ? (
                <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 text-destructive" aria-hidden="true" />
                  <div className="text-destructive">{taskResult?.message || t('catalogImport.failed')}</div>
                </div>
              ) : null}
            </CardContent>
          </Card>
        ) : null}

        <Card className="border-dashed">
          <CardContent className="p-5">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <FileSpreadsheet className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              {t('catalogImport.requirements')}
            </h3>
            <ul className="space-y-1 text-xs text-muted-foreground">
              <li>• {t('catalogImport.req1')}</li>
              <li>• {t('catalogImport.req2')}</li>
              <li>• {t('catalogImport.req3')}</li>
              <li>• {t('catalogImport.req4')}</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

function Stat({ label, value, tone }: { label: string; value?: number | null; tone?: 'warn' }) {
  return (
    <div className="rounded-md border border-border p-2 text-center">
      <div className={`text-lg font-bold tabular-nums ${tone === 'warn' ? 'text-warning' : 'text-foreground'}`}>
        {value ?? 0}
      </div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

export default CatalogImportPage;
