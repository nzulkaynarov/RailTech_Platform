import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Download, Loader2 } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import { isPortalApiError, type PriceListReport } from '@/api/portal';
import { keys, usePriceListTask, useUploadPriceList } from '@/api/queries';
import { DateField } from '@/components/DateField';
import { FileField } from '@/components/FileField';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { downloadTemplate, priceFileProblem } from '@/lib/priceList';
import { toast } from '@/lib/toast';
import { PriceListReportView } from './PriceListReport';

interface Run {
  taskId: string;
  dryRun: boolean;
}

/**
 * Мастер загрузки прайса: файл и срок цен → проверка (предпросмотр с ошибками по строкам, ничего не записано) → «Загрузить» →
 * отчёт. Состояние шага выводится из задачи ERP (`usePriceListTask`), своих флагов «завершено» нет.
 */
export function PriceListWizard({ open, onOpenChange, onGoDrafts }: { open: boolean; onOpenChange: (open: boolean) => void; onGoDrafts: () => void }) {
  const { t } = useTranslation();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl" aria-describedby={undefined}>
        <SheetHeader>
          <SheetTitle>{t('partner.wizard.title')}</SheetTitle>
          <SheetDescription>{t('partner.wizard.description')}</SheetDescription>
        </SheetHeader>
        {/* Содержимое монтируется только пока мастер открыт: закрытие сбрасывает файл, даты и задачу */}
        {open ? <WizardBody onClose={() => onOpenChange(false)} onGoDrafts={onGoDrafts} /> : null}
      </SheetContent>
    </Sheet>
  );
}

function WizardBody({ onClose, onGoDrafts }: { onClose: () => void; onGoDrafts: () => void }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const fileId = useId();
  const fromId = useId();
  const untilId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [from, setFrom] = useState<string | null>('');
  const [until, setUntil] = useState<string | null>('');
  const [run, setRun] = useState<Run | null>(null);
  const upload = useUploadPriceList();
  const task = usePriceListTask(run?.taskId ?? null);

  const problem = file ? priceFileProblem(file) : null;
  const dateProblem = from === null || until === null ? 'dateInvalid' : from && until && until < from ? 'rangeInvalid' : null;
  const ready = file !== null && problem === null && dateProblem === null;

  const start = (dryRun: boolean) => {
    if (!file) return;
    upload.mutate(
      { file, dryRun, validFrom: from || undefined, validUntil: until || undefined },
      {
        onSuccess: (taskId) => {
          setRun({ taskId, dryRun });
        },
      },
    );
  };

  const reset = () => {
    setRun(null);
    setFile(null);
    upload.reset();
  };

  const status = run ? (task.data?.status ?? 'pending') : null;
  const finished = status === 'completed' || status === 'failed';
  // Записанные карточки и цены — в список «Мои товары»
  const applied = run !== null && !run.dryRun && status === 'completed';
  useEffect(() => {
    if (applied) void client.invalidateQueries({ queryKey: keys.partnerProducts });
  }, [applied, client]);

  const downloadError = (message: string) => toast.error(message);

  return (
    <div className="flex flex-col gap-5 px-4 pb-6">
      <ol aria-label={t('partner.wizard.stepsLabel')} className="flex items-center gap-2 text-xs text-muted-foreground">
        {(['file', 'check', 'done'] as const).map((step, index) => {
          const current = !run ? 0 : !finished ? 1 : run.dryRun ? 1 : 2;
          return (
            <li key={step} aria-current={index === current ? 'step' : undefined} className={index === current ? 'font-semibold text-primary' : undefined}>
              {index + 1}. {t(`partner.wizard.steps.${step}`)}
            </li>
          );
        })}
      </ol>

      {!run ? (
        <>
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">{t('partner.wizard.template')}</h3>
            <p className="text-sm text-muted-foreground">{t('partner.wizard.templateText')}</p>
            <div>
              <Button type="button" variant="outline" size="sm" onClick={() => void downloadTemplate(downloadError, t('partner.templateFailed'))}>
                <Download aria-hidden="true" />
                {t('partner.downloadTemplate')}
              </Button>
            </div>
          </section>

          <section className="flex flex-col gap-2">
            <Label htmlFor={fileId} className="text-sm font-semibold">
              {t('partner.wizard.chooseFile')}
            </Label>
            <FileField id={fileId} value={file} onChange={setFile} accept=".xlsx" invalid={problem !== null} />
            <p className="text-xs text-muted-foreground">{t('partner.wizard.fileHint')}</p>
            {problem ? (
              <p role="alert" className="text-sm text-destructive">
                {t(`partner.wizard.${problem}`)}
              </p>
            ) : null}
          </section>

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">{t('partner.wizard.validity')}</h3>
            <p className="text-xs text-muted-foreground">{t('partner.wizard.validityText')}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={fromId}>{t('partner.wizard.validFrom')}</Label>
                <DateField id={fromId} value={from} onChange={setFrom} invalid={from === null} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={untilId}>{t('partner.wizard.validUntil')}</Label>
                <DateField id={untilId} value={until} onChange={setUntil} invalid={until === null || dateProblem === 'rangeInvalid'} />
              </div>
            </div>
            {dateProblem ? (
              <p role="alert" className="text-sm text-destructive">
                {t(`partner.wizard.${dateProblem}`)}
              </p>
            ) : null}
          </section>

          {upload.isError ? (
            <Alert variant="destructive">
              <AlertTriangle aria-hidden="true" />
              <AlertDescription>
                {isPortalApiError(upload.error) && upload.error.code === 'FILE_TOO_LARGE' ? t('partner.wizard.tooLarge') : t(apiErrorKey(upload.error))}
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="button" disabled={!ready || upload.isPending} onClick={() => start(true)}>
              {upload.isPending ? <Loader2 className="motion-safe:animate-spin" aria-hidden="true" /> : null}
              {t('partner.wizard.check')}
            </Button>
          </div>
        </>
      ) : !finished ? (
        <div role="status" aria-live="polite" className="flex flex-col items-center gap-2 py-10 text-center">
          <Loader2 className="size-6 text-primary motion-safe:animate-spin" aria-hidden="true" />
          <p className="font-medium">{run.dryRun ? t('partner.wizard.checking') : t('partner.wizard.loading')}</p>
          <p className="text-sm text-muted-foreground">{run.dryRun ? t('partner.wizard.checkingText') : t('partner.wizard.loadingText')}</p>
        </div>
      ) : task.data?.status === 'failed' || !task.data?.report ? (
        <div className="flex flex-col gap-3">
          <Alert variant="destructive">
            <AlertTriangle aria-hidden="true" />
            <AlertDescription>
              <p className="font-medium">{t('partner.wizard.failedTitle')}</p>
              <p>{failedText(task.data?.error ?? null, t)}</p>
            </AlertDescription>
          </Alert>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              {t('partner.wizard.closeBtn')}
            </Button>
            <Button type="button" onClick={reset}>
              {t('partner.wizard.retry')}
            </Button>
          </div>
        </div>
      ) : run.dryRun ? (
        <Preview
          report={task.data.report}
          pending={upload.isPending}
          onLoad={() => start(false)}
          onAnother={reset}
          error={upload.isError ? t(apiErrorKey(upload.error)) : null}
        />
      ) : (
        <Done report={task.data.report} onClose={onClose} onGoDrafts={onGoDrafts} />
      )}
    </div>
  );
}

function failedText(error: string | null, t: (key: string) => string): string {
  if (error === 'NAME_COLUMN_NOT_FOUND') return t('partner.wizard.failedCode.NAME_COLUMN_NOT_FOUND');
  return t('partner.wizard.failedCode.IMPORT_FAILED');
}

function Preview({
  report,
  pending,
  error,
  onLoad,
  onAnother,
}: {
  report: PriceListReport;
  pending: boolean;
  error: string | null;
  onLoad: () => void;
  onAnother: () => void;
}) {
  const { t } = useTranslation();
  const loadable = report.created + report.updated > 0;
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="text-base font-semibold">{t('partner.wizard.previewTitle')}</h3>
        {report.error_count > 0 ? (
          <p className="text-sm text-muted-foreground">{t('partner.wizard.previewWithErrors', { count: report.error_count })}</p>
        ) : null}
        {!loadable ? <p className="text-sm text-destructive">{t('partner.wizard.nothingToLoad')}</p> : null}
      </div>
      <PriceListReportView report={report} final={false} />
      {error ? (
        <Alert variant="destructive">
          <AlertTriangle aria-hidden="true" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" onClick={onAnother} disabled={pending}>
          {t('partner.wizard.chooseAnother')}
        </Button>
        <Button type="button" onClick={onLoad} disabled={!loadable || pending}>
          {pending ? <Loader2 className="motion-safe:animate-spin" aria-hidden="true" /> : null}
          {report.error_count > 0 ? t('partner.wizard.loadWithSkipped') : t('partner.wizard.load')}
        </Button>
      </div>
    </div>
  );
}

function Done({ report, onClose, onGoDrafts }: { report: PriceListReport; onClose: () => void; onGoDrafts: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4">
      <div role="status" className="flex items-start gap-3">
        <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-hidden="true" />
        <div>
          <h3 className="text-base font-semibold">{t('partner.wizard.doneTitle')}</h3>
          <p className="text-sm text-muted-foreground">{t('partner.wizard.doneText')}</p>
        </div>
      </div>
      <PriceListReportView report={report} final />
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" onClick={onClose}>
          {t('partner.wizard.closeBtn')}
        </Button>
        <Button type="button" onClick={onGoDrafts}>
          {t('partner.wizard.goDrafts')}
        </Button>
      </div>
    </div>
  );
}
