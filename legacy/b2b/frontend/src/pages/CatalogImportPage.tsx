import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Package, Upload, FileSpreadsheet, Download, CheckCircle2, Loader2, AlertCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { PageShell } from './shared/PageShell';
import { sourcingApi } from '@/api/sourcingApi';
import { translateApiError } from '@/lib/apiError';

type TaskStatus = 'PENDING' | 'STARTED' | 'PROGRESS' | 'SUCCESS' | 'FAILURE' | 'REVOKED' | string;

/**
 * SELLER / MANUFACTURER self-serve catalog bulk import. Posts to
 * `/sourcing/import-catalog/` (member-gated), polls task status, shows
 * progress + final result. Admin is auto-notified via ImportTask.owner
 * + Celery activity — no separate admin action required.
 */
export function CatalogImportPage() {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [taskResult, setTaskResult] = useState<unknown>(null);
  const [taskMeta, setTaskMeta] = useState<{ current?: number; total?: number } | null>(null);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Poll the Celery task status while it's running.
  useEffect(() => {
    if (!taskId) return;
    const isTerminal = (s: TaskStatus | null) =>
      s === 'SUCCESS' || s === 'FAILURE' || s === 'REVOKED';
    if (isTerminal(taskStatus)) return;

    let cancelled = false;
    const tick = async () => {
      try {
        const data = await sourcingApi.getImportStatus(taskId);
        if (cancelled) return;
        setTaskStatus(data.status);
        setTaskMeta(data.meta ?? null);
        if (data.status === 'SUCCESS') setTaskResult(data.result);
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

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setTaskId(null);
    setTaskStatus(null);
    setTaskResult(null);
    setTaskMeta(null);
    try {
      const { task_id } = await sourcingApi.importCatalog(file);
      setTaskId(task_id);
      setTaskStatus('PENDING');
      toast.success(t('catalogImport.queued'));
    } catch (e) {
      toast.error(translateApiError(e));
    } finally {
      setUploading(false);
    }
  }

  function downloadTemplate() {
    window.open(
      `${window.location.origin}/api/v1/catalog/products/export-template/`,
      '_blank',
      'noopener',
    );
  }

  const isTerminal = taskStatus === 'SUCCESS' || taskStatus === 'FAILURE' || taskStatus === 'REVOKED';
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
      <div className="max-w-2xl space-y-6">
        <Card>
          <CardContent className="space-y-3 p-5">
            <div className="flex items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Badge variant="outline" className="text-xs">1</Badge>
                {t('catalogImport.template')}
              </h3>
              <Button
                size="sm"
                variant="outline"
                className="gap-1.5 text-xs"
                onClick={downloadTemplate}
              >
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
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
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
            <Button
              className="w-full"
              disabled={!file || uploading}
              onClick={handleUpload}
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : null}
              {t('catalogImport.startImport')}
            </Button>
          </CardContent>
        </Card>

        {taskId ? (
          <Card>
            <CardContent className="space-y-2 p-5">
              <div className="flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold">
                  <Badge variant="outline" className="text-xs">3</Badge>
                  {t('catalogImport.progress')}
                </h3>
                <Badge variant={taskStatus === 'SUCCESS' ? 'default' : taskStatus === 'FAILURE' ? 'destructive' : 'secondary'}>
                  {taskStatus ?? 'PENDING'}
                </Badge>
              </div>
              <Progress value={progress} className="h-2" />
              {taskMeta?.current != null && taskMeta.total ? (
                <p className="text-xs tabular-nums text-muted-foreground">
                  {taskMeta.current} / {taskMeta.total}
                </p>
              ) : null}
              {isTerminal && taskStatus === 'SUCCESS' ? (
                <div className="flex items-start gap-2 rounded-md border border-success/40 bg-success/5 p-3 text-xs">
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 text-success" aria-hidden="true" />
                  <div>
                    <div className="font-medium text-success">
                      {t('catalogImport.successTitle')}
                    </div>
                    <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-muted-foreground">
                      {typeof taskResult === 'string' ? taskResult : JSON.stringify(taskResult, null, 2)}
                    </pre>
                  </div>
                </div>
              ) : null}
              {isTerminal && taskStatus !== 'SUCCESS' ? (
                <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 text-destructive" aria-hidden="true" />
                  <div className="text-destructive">{t('catalogImport.failed')}</div>
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

export default CatalogImportPage;
