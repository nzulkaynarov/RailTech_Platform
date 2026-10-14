import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Package, Upload, FileSpreadsheet, Download, CheckCircle2, Loader2, AlertCircle, AlertTriangle, SearchCheck, Sparkles } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { PageShell } from './shared/PageShell';
import { sourcingApi, type CatalogImportResult, type CatalogImportRowMessage } from '@/api/sourcingApi';
import { translateApiError } from '@/lib/apiError';
import { runAiJob } from '@/lib/aiJob';

type TaskStatus = 'PENDING' | 'STARTED' | 'PROGRESS' | 'SUCCESS' | 'FAILURE' | 'REVOKED' | string;

/**
 * Коды с параметром после двоеточия (`CODE:значение`) — значение подставляется в `{{code}}`.
 * Единая таблица вместо цепочки `startsWith`: новый код бэкенда добавляется одной строкой,
 * и невозможно забыть про него ветку.
 */
const PARAMETERIZED_MESSAGE_KEYS: Record<string, string> = {
  UNKNOWN_CURRENCY: 'catalogImport.err.unknownCurrency',
  UNKNOWN_STOCK_STATUS: 'catalogImport.err.unknownStock',
  UNKNOWN_CATEGORY: 'catalogImport.err.unknownCategory',
  UNKNOWN_DOMAIN: 'catalogImport.err.unknownDomain',
  HS_CODE_NOT_IN_CLASSIFIER: 'catalogImport.err.hsCodeNotInClassifier',
  HS_CODE_RETIRED: 'catalogImport.err.hsCodeRetired',
  HS_CODE_TOO_LONG: 'catalogImport.err.hsCodeTooLong',
};

/** Коды без параметра. */
const PLAIN_MESSAGE_KEYS: Record<string, string> = {
  PRICE_NOT_A_NUMBER: 'catalogImport.err.badPrice',
  PRICE_NOT_POSITIVE: 'catalogImport.err.priceNotPositive',
  NAME_COLUMN_NOT_FOUND: 'catalogImport.err.nameColumnNotFound',
  ROW_FAILED: 'catalogImport.err.rowFailed',
  // ИИ-путь может вернуть штатный отчёт со status=error и этим кодом в message —
  // переводим той же таблицей, ключ живёт в общем словаре apiErrors.
  AI_EXTRACT_EMPTY: 'apiErrors.AI_EXTRACT_EMPTY',
};

/** Файлы, которые идут СТАРЫМ (бесплатным, шаблонным) путём; всё остальное разбирает ИИ. */
const XLSX_FILE_RE = /\.xlsx$/i;
/** Форматы, которые принимает вход (xlsx — шаблонный путь; pdf/фото — ИИ). */
const ACCEPTED_FORMATS = '.xlsx,.pdf,.png,.jpg,.jpeg';

/** Похоже ли начало сообщения на машинный код, а не на готовую фразу сервера. */
const MACHINE_CODE_RE = /^[A-Z][A-Z0-9_]*$/;

/**
 * Переводит сообщение бэкенда (ошибку строки, замечание или фатальную ошибку файла)
 * в человеческий текст.
 *
 * Незнакомый код НЕ выдаётся за перевод: он показывается как есть внутри честной
 * обёртки «неизвестная причина», чтобы поддержка увидела код, а пользователь понял,
 * что это не текст для него. Не-код (готовая фраза сервера) возвращается без изменений.
 */
function useImportMessageText() {
  const { t } = useTranslation();
  return (message: string): string => {
    const raw = (message ?? '').trim();
    if (!raw) return '';
    const separator = raw.indexOf(':');
    const code = separator === -1 ? raw : raw.slice(0, separator).trim();
    const value = separator === -1 ? '' : raw.slice(separator + 1).trim();

    if (separator !== -1) {
      const parameterizedKey = PARAMETERIZED_MESSAGE_KEYS[code];
      if (parameterizedKey) return t(parameterizedKey, { code: value });
    }
    const plainKey = PLAIN_MESSAGE_KEYS[code];
    if (plainKey) return value ? `${t(plainKey)}: ${value}` : t(plainKey);

    if (MACHINE_CODE_RE.test(code)) return t('catalogImport.err.unknownCode', { code: raw });
    return raw;
  };
}

/**
 * SELLER / MANUFACTURER self-serve catalog bulk import (true-PIM). One file input
 * accepts any price list (Shopify-import pattern), the routing is backstage:
 * `.xlsx` goes the old free path (`/sourcing/import-catalog/` + import-status polling),
 * anything else (PDF/photo) goes `/sourcing/import-catalog-ai/` + `runAiJob` polling —
 * the AI extracts rows and the worker returns the SAME import report shape.
 * Both paths keep the two-step flow: a dry-run "check" that previews counts + row
 * errors without persisting, then the real import. The uploader's company is the
 * supplier on every offer.
 */
export function CatalogImportPage() {
  const { t } = useTranslation();
  const importMessageText = useImportMessageText();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  /** Каким путём пошёл ТЕКУЩИЙ запуск (не выбранный файл): 'xlsx' — шаблонный, 'ai' — ИИ. */
  const [route, setRoute] = useState<'xlsx' | 'ai' | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [taskResult, setTaskResult] = useState<CatalogImportResult | null>(null);
  const [taskMeta, setTaskMeta] = useState<{ current?: number; total?: number } | null>(null);
  const [busy, setBusy] = useState<'check' | 'import' | null>(null);
  /**
   * Опрос статуса перестал получать ответы. Раньше сбой статус-эндпоинта означал, что прогресс
   * замирал НАВСЕГДА: задача в Celery могла давно завершиться, а пользователь смотрел на
   * застывшую полосу и не знал, ждать ему или начинать заново (аудит UI, U2).
   */
  const [pollLost, setPollLost] = useState(false);
  /** Счётчик ручных попыток — его смена перезапускает эффект опроса. */
  const [pollAttempt, setPollAttempt] = useState(0);
  const [checkedOk, setCheckedOk] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  /**
   * Общая посадка результата для ОБОИХ путей: удачная проверка открывает кнопку
   * импорта, настоящий импорт сбрасывает кэш списка товаров (см. комментарий ниже).
   */
  const applyImportResult = useCallback(
    (result: CatalogImportResult | null) => {
      setTaskResult(result);
      if (result?.dry_run && result?.status === 'success') setCheckedOk(true);
      // Настоящий импорт создал карточки МИМО React Query, поэтому список товаров о них
      // не знает и по `staleTime` отдаёт прежний ответ. Без сброса продавец уходил в
      // «Каталог» сразу после загрузки и своих новых позиций там не видел — поймано
      // проходом глазами. Проверка (dry-run) ничего не пишет, ей сбрасывать нечего.
      if (!result?.dry_run && result?.status === 'success') {
        queryClient.invalidateQueries({ queryKey: ['products'] });
      }
    },
    [queryClient],
  );

  // Poll the Celery task status while it's running (xlsx path only; the AI path
  // is awaited straight through runAiJob and never sets taskId).
  useEffect(() => {
    if (!taskId) return;
    const isTerminal = (s: TaskStatus | null) => s === 'SUCCESS' || s === 'FAILURE' || s === 'REVOKED';
    if (isTerminal(taskStatus)) return;

    let cancelled = false;
    // Одиночный сбой — обычное дело (перезапуск бэкенда, потеря сети); сдаёмся только после
    // серии подряд, чтобы не пугать пользователя миганием.
    const MAX_CONSECUTIVE_FAILURES = 5;
    let consecutiveFailures = 0;
    const tick = async () => {
      try {
        const data = await sourcingApi.getImportStatus(taskId);
        if (cancelled) return;
        consecutiveFailures = 0;
        setPollLost(false);
        setTaskStatus(data.status);
        setTaskMeta(data.meta ?? null);
        if (data.status === 'SUCCESS') {
          applyImportResult(data.result ?? null);
        }
      } catch {
        if (cancelled) return;
        consecutiveFailures += 1;
        if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) setPollLost(true);
      }
    };
    const interval = setInterval(tick, 2000);
    tick();
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [taskId, taskStatus, pollAttempt, applyImportResult]);

  function pickFile(next: File | null) {
    setFile(next);
    setCheckedOk(false);
    setRoute(null);
    setTaskId(null);
    setTaskStatus(null);
    setTaskResult(null);
    setTaskMeta(null);
    setPollLost(false);
  }

  async function runImport(dryRun: boolean) {
    if (!file) return;
    // Маршрутизация за кулисами: .xlsx — старый бесплатный путь, остальное разбирает ИИ.
    const aiRoute = !XLSX_FILE_RE.test(file.name);
    setBusy(dryRun ? 'check' : 'import');
    setRoute(aiRoute ? 'ai' : 'xlsx');
    setTaskId(null);
    setTaskStatus(null);
    setTaskResult(null);
    setTaskMeta(null);
    setPollLost(false);
    try {
      if (aiRoute) {
        // ИИ-путь опрашивается через ai-status (runAiJob), а не import-status:
        // ждём результат прямо здесь, прогресс — неопределённый лоадер в карточке отчёта.
        setTaskStatus('PROGRESS');
        const result = await runAiJob<CatalogImportResult>(() => sourcingApi.importCatalogAi(file, dryRun));
        setTaskStatus('SUCCESS');
        applyImportResult(result);
      } else {
        const { task_id } = await sourcingApi.importCatalog(file, dryRun);
        setTaskId(task_id);
        setTaskStatus('PENDING');
        toast.success(dryRun ? t('catalogImport.checkQueued') : t('catalogImport.queued'));
      }
    } catch (e) {
      if (aiRoute) {
        // Карточка отчёта уже на экране («ИИ разбирает файл…») — оставляем причину и в ней,
        // а не только в исчезающем тосте. Текст уже переведён, машинный код сюда не попадает
        // (перевод падает в сам код только пока ключ не доехал до локали — честная деградация).
        setTaskStatus('FAILURE');
        setTaskResult({ status: 'error', message: translateApiError(e) });
      }
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
      anchor.download = 'catalog_template.xlsx';
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
  const warnings = taskResult?.warnings ?? [];
  // Списки строк усечены сервером, а счётчики продолжают считать. Раньше экран
  // показывал только усечённый список и молча выдавал его за полный.
  const errorCount = taskResult?.error_count ?? errors.length;
  const warningCount = taskResult?.warning_count ?? warnings.length;
  const rowsTruncated = taskResult?.rows_truncated ?? 0;
  /** `null` — бэкенд старше бандла и порог публикации не считал: врать нечем, блок скрываем. */
  const unpublishable = typeof taskResult?.unpublishable === 'number' ? taskResult.unpublishable : null;
  const missingBreakdown = taskResult?.missing_breakdown ?? [];
  const touchedCards = (taskResult?.created ?? 0) + (taskResult?.updated ?? 0);
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
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Upload className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              {t('catalogImport.uploadAnyTitle')}
            </h3>
            <p className="text-xs text-muted-foreground">{t('catalogImport.uploadAnyHint')}</p>
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPTED_FORMATS}
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
            {/* Скромная пометка: не-Excel файл разберёт ИИ. Пользователю не нужно знать про два пути. */}
            {file && !XLSX_FILE_RE.test(file.name) ? (
              <p className="flex items-center gap-1.5 text-xs text-info">
                <Sparkles className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {t('catalogImport.aiWillParse')}
              </p>
            ) : null}
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
            {/* Шаблон — второстепенная ссылка, а не первый шаг: любой прайс разберёт ИИ. */}
            <Button
              variant="link"
              size="sm"
              className="h-auto gap-1.5 p-0 text-xs text-muted-foreground"
              onClick={downloadTemplate}
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              {t('catalogImport.templateSecondary')}
            </Button>
          </CardContent>
        </Card>

        {taskId || route === 'ai' ? (
          <Card>
            <CardContent className="space-y-3 p-5">
              <div className="flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold">
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
              {route === 'ai' ? (
                // У ИИ-пути нет счётчика строк (ai-status не отдаёт meta) — честный
                // неопределённый лоадер вместо придуманного процента.
                !isTerminal ? (
                  <div className="flex items-center gap-3 rounded-md border border-border p-3">
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" aria-hidden="true" />
                    <span className="text-xs text-muted-foreground">{t('catalogImport.aiParsing')}</span>
                  </div>
                ) : null
              ) : (
                <>
                  <Progress value={progress} className="h-2" />
                  {taskMeta?.current != null && taskMeta.total ? (
                    <p className="text-xs tabular-nums text-muted-foreground">
                      {taskMeta.current} / {taskMeta.total}
                    </p>
                  ) : null}
                </>
              )}

              {pollLost && !isTerminal ? (
                <div className="flex items-center gap-3 rounded-md border border-warning/30 bg-warning/5 p-3">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                  <span className="min-w-0 flex-1 text-xs text-foreground">{t('catalogImport.statusLost')}</span>
                  <Button variant="outline" size="sm" onClick={() => { setPollLost(false); setPollAttempt((n) => n + 1); }}>
                    {t('common.retry')}
                  </Button>
                </div>
              ) : null}

              {isTerminal && taskStatus === 'SUCCESS' && !isError ? (
                <div className="space-y-3">
                  {rowsTruncated > 0 ? (
                    <div className="flex items-start gap-3 rounded-md border-2 border-warning/50 bg-warning/10 p-3">
                      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
                      <div className="min-w-0 flex-1 space-y-1">
                        <p className="text-sm font-semibold text-warning tabular-nums">
                          {t('catalogImport.rowsTruncatedTitle', { n: rowsTruncated })}
                        </p>
                        <p className="text-xs text-foreground">{t('catalogImport.rowsTruncatedHint')}</p>
                      </div>
                    </div>
                  ) : null}

                  {/* Строки извлёк ИИ, а не шаблонный парсер — предпросмотр надо смотреть внимательнее. */}
                  {taskResult?.ai_used ? (
                    <div className="flex items-start gap-2 rounded-md border border-info/40 bg-info/5 p-3 text-xs">
                      <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" aria-hidden="true" />
                      <div className="text-foreground">
                        {t('catalogImport.aiUsedNotice', { n: taskResult?.ai_rows ?? 0 })}
                      </div>
                    </div>
                  ) : null}

                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <Stat label={t('catalogImport.stat.created')} value={taskResult?.created} />
                    <Stat label={t('catalogImport.stat.updated')} value={taskResult?.updated} />
                    <Stat label={t('catalogImport.stat.offers')} value={taskResult?.offers_upserted} />
                    <Stat label={t('catalogImport.stat.skipped')} value={taskResult?.skipped} tone="warn" />
                  </div>

                  {/*
                    Главное число экрана: сколько карточек нельзя будет опубликовать.
                    Без него продавец создавал 3000 карточек и узнавал о непроходимом
                    пороге по одной карточке за раз.
                  */}
                  {unpublishable !== null && unpublishable > 0 ? (
                    <div className="rounded-md border-2 border-warning/50 bg-warning/10 p-4">
                      <div className="flex items-start gap-3">
                        <AlertTriangle className="mt-1 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
                        <div className="min-w-0 flex-1 space-y-1">
                          <p className="text-2xl font-bold tabular-nums text-warning">{unpublishable}</p>
                          <p className="text-sm font-semibold text-foreground">
                            {t('catalogImport.unpublishableTitle')}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {taskResult?.dry_run
                              ? t('catalogImport.unpublishableHintDryRun')
                              : t('catalogImport.unpublishableHint')}
                          </p>
                        </div>
                      </div>
                      {missingBreakdown.length > 0 ? (
                        <div className="mt-3 space-y-1 border-t border-warning/30 pt-3">
                          <p className="text-xs font-medium text-foreground">
                            {t('catalogImport.missingBreakdownTitle')}
                          </p>
                          <ul className="space-y-1">
                            {missingBreakdown.map((requirement) => (
                              <li
                                key={requirement.code}
                                className="flex items-center justify-between gap-3 text-xs"
                              >
                                {/* label приходит уже переведённым сервером — через t() не гоняем */}
                                <span className="min-w-0 truncate text-foreground">{requirement.label}</span>
                                <span className="shrink-0 tabular-nums text-muted-foreground">
                                  {t('catalogImport.missingOnCards', { n: requirement.count })}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {/* Хвалить нечего, если карточек вообще нет: «все пройдут порог» при нуле — ложь. */}
                  {unpublishable === 0 && touchedCards > 0 ? (
                    <div className="flex items-start gap-2 rounded-md border border-success/40 bg-success/5 p-3 text-xs">
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden="true" />
                      <div className="text-foreground">{t('catalogImport.allPublishable')}</div>
                    </div>
                  ) : null}

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
                        {t('catalogImport.errorsTitle', { count: errorCount })}
                      </p>
                      <p className="text-xs text-muted-foreground">{t('catalogImport.errorsHint')}</p>
                      <RowMessageTable
                        rows={errors}
                        rowLabel={t('catalogImport.errRow')}
                        reasonLabel={t('catalogImport.errReason')}
                        format={importMessageText}
                      />
                      {errorCount > errors.length ? (
                        <p className="text-xs text-muted-foreground">
                          {t('catalogImport.shownFirst', { shown: errors.length, total: errorCount })}
                        </p>
                      ) : null}
                    </div>
                  ) : null}

                  {/* Замечания — НЕ отказы: строка загружена, но к ней есть вопрос. */}
                  {warnings.length > 0 ? (
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-warning">
                        {t('catalogImport.warningsTitle', { n: warningCount })}
                      </p>
                      <p className="text-xs text-muted-foreground">{t('catalogImport.warningsHint')}</p>
                      <RowMessageTable
                        rows={warnings}
                        rowLabel={t('catalogImport.errRow')}
                        reasonLabel={t('catalogImport.warnReason')}
                        format={importMessageText}
                      />
                      {warningCount > warnings.length ? (
                        <p className="text-xs text-muted-foreground">
                          {t('catalogImport.shownFirst', { shown: warnings.length, total: warningCount })}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {(isTerminal && taskStatus !== 'SUCCESS') || isError ? (
                <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden="true" />
                  {/* Фатальная ошибка файла (например, NAME_COLUMN_NOT_FOUND) приходит тем же
                      машинным кодом — переводим её той же таблицей, а не печатаем код в лицо. */}
                  <div className="text-destructive">
                    {taskResult?.message ? importMessageText(taskResult.message) : t('catalogImport.failed')}
                  </div>
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
              <li>• {t('catalogImport.reqFormats')}</li>
              <li>• {t('catalogImport.req2')}</li>
              <li>• {t('catalogImport.req3')}</li>
              <li>• {t('catalogImport.req5')}</li>
              <li>• {t('catalogImport.req4')}</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

/** Таблица «строка файла → причина». Одна разметка на ошибки и на замечания. */
function RowMessageTable({
  rows,
  rowLabel,
  reasonLabel,
  format,
}: {
  rows: CatalogImportRowMessage[];
  rowLabel: string;
  reasonLabel: string;
  format: (message: string) => string;
}) {
  return (
    <div className="max-h-48 overflow-auto rounded-md border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-20">{rowLabel}</TableHead>
            <TableHead>{reasonLabel}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {/* На одну строку файла может прийти несколько сообщений — ключ по номеру строки не уникален. */}
          {rows.map((rowMessage, index) => (
            <TableRow key={`${rowMessage.row}-${index}`}>
              <TableCell className="tabular-nums text-muted-foreground">{rowMessage.row}</TableCell>
              <TableCell>{format(rowMessage.message)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
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
