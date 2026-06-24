import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileSpreadsheet, X, Loader2, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { crmApi } from '../../api/crmApi';
import { useTaskStore, type TaskResult } from '../../store/taskStore';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Alert, AlertDescription } from '@/components/ui/alert';

interface ExcelUploadProps {
    dealId: number;
    /** Fires only when the import task COMPLETES (not on enqueue). Carries the
     *  task summary (rows added / merged) so the caller can report real counts. */
    onUploadSuccess?: (summary?: TaskResult) => void;
    // AI mode: accept ANY supported file (Excel/CSV/PDF/image/text); Claude maps it.
    useAI?: boolean;
}

const AI_ACCEPT = '.xlsx,.xls,.csv,.tsv,.txt,.pdf,.png,.jpg,.jpeg,.webp,.gif';
const AI_EXT = /\.(xlsx|xls|csv|tsv|txt|pdf|png|jpe?g|webp|gif)$/i;

export const ExcelUpload: React.FC<ExcelUploadProps> = ({ dealId, onUploadSuccess, useAI = false }) => {
    const { t } = useTranslation();
    const [file, setFile] = useState<File | null>(null);
    const [isDispatching, setIsDispatching] = useState(false);
    const [isDragActive, setIsDragActive] = useState(false);
    const [error, setError] = useState<string | null>(null);
    // canRetry distinguishes a recoverable import failure (dispatch error or task
    // FAILURE — same file can be re-sent) from a validation error (must pick a
    // different file). lastFileRef keeps the dispatched file so retry needs no
    // re-selection (it's cleared from `file` state once the import is enqueued).
    const [canRetry, setCanRetry] = useState(false);
    const lastFileRef = useRef<File | null>(null);
    const [taskId, setTaskId] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { addTask, tasks } = useTaskStore();

    const task = taskId ? tasks[taskId] : null;
    const isImporting = !!task && (task.status === 'PENDING' || task.status === 'PROGRESS');
    // The deterministic parser reports real current/total rows; AI/PDF jobs have
    // no granular signal. Rather than fake a climbing % that stalls at the end,
    // show a real bar ONLY when there's real progress, and an honest elapsed
    // timer otherwise — never a number that pretends to know how far along it is.
    const hasRealProgress = !!task?.progress && task.progress.total > 0;
    // Safe percent: guard against a missing/zero total (division would yield
    // NaN/Infinity and break the Progress bar) — fall back to 0.
    const progressTotal = task?.progress?.total;
    const progressPercent = progressTotal ? Math.round(((task?.progress?.current ?? 0) / progressTotal) * 100) : 0;
    const [elapsedSec, setElapsedSec] = useState(0);
    useEffect(() => {
        if (!isImporting) { setElapsedSec(0); return; }
        const id = setInterval(() => setElapsedSec((s) => s + 1), 1000);
        return () => clearInterval(id);
    }, [isImporting]);
    const elapsedLabel = `${Math.floor(elapsedSec / 60)}:${String(elapsedSec % 60).padStart(2, '0')}`;

    // Success/failure are driven by the POLLED task status — not by enqueue. The
    // parent only learns the import is done once the items actually exist.
    useEffect(() => {
        if (!task) return;
        if (task.status === 'SUCCESS') {
            const summary = task.result ?? undefined;
            setTaskId(null);
            onUploadSuccess?.(summary);
        } else if (task.status === 'FAILURE') {
            const message = task.error || t('sourcing.uploadError');
            setError(message);
            setCanRetry(true); // same file can be re-sent
            toast.error(message);
            setTaskId(null);
        }
    }, [task?.status]); // eslint-disable-line react-hooks/exhaustive-deps

    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragActive(e.type === 'dragenter' || e.type === 'dragover');
    };

    const validateFile = (candidate: File) => {
        const ok = useAI
            ? AI_EXT.test(candidate.name)
            : ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel'].includes(candidate.type);
        if (!ok) {
            setError(t('sourcing.uploadError'));
            setCanRetry(false); // wrong file type — retrying the same file won't help
            return false;
        }
        setError(null);
        return true;
    };

    const pickFile = (candidate?: File | null) => {
        if (candidate && validateFile(candidate)) setFile(candidate);
    };

    const dispatchImport = async (toSend: File) => {
        lastFileRef.current = toSend;
        setIsDispatching(true);
        setError(null);
        setCanRetry(false);
        try {
            const result = await crmApi.importExcelToDeal(dealId, toSend, useAI);
            addTask(result.task_id, 'excel_import');
            setTaskId(result.task_id); // success/failure handled by the polled status
            setFile(null);
        } catch (e) {
            const message = translateApiError(e);
            setError(message);
            setCanRetry(true); // enqueue failed (e.g. broker down) — same file can be re-sent
            toast.error(message);
        } finally {
            setIsDispatching(false);
        }
    };

    const handleUpload = () => {
        if (file) dispatchImport(file);
    };

    const handleRetry = () => {
        if (lastFileRef.current) dispatchImport(lastFileRef.current);
    };

    const acceptText = useAI ? t('aiImport.acceptedAi') : '.xlsx, .xls';

    return (
        // min-w-0: DialogContent is a CSS grid, whose children default to
        // min-width:auto — a long unbreakable filename would otherwise force the
        // whole dialog wider than the viewport and push the upload button
        // off-screen (unclickable). min-w-0 lets the row shrink so truncate works.
        <div className="w-full min-w-0 space-y-3">
            {/* Importing — driven by polled task status */}
            {isImporting ? (
                <div className="rounded-xl border border-border p-5">
                    <div className="mb-2 flex items-center justify-between gap-2 text-sm font-medium">
                        <span className="flex min-w-0 items-center gap-2">
                            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" aria-hidden="true" />
                            <span className="truncate">{t('sourcing.processing')}</span>
                        </span>
                        <span className="shrink-0 text-xs font-normal text-muted-foreground tabular-nums">{elapsedLabel}</span>
                    </div>
                    {hasRealProgress ? (
                        <>
                            <Progress value={progressPercent} />
                            <p className="mt-1 text-right text-xs text-muted-foreground tabular-nums">
                                {task?.progress?.current ?? 0} / {task?.progress?.total ?? 0}
                            </p>
                        </>
                    ) : (
                        <p className="text-xs text-muted-foreground">{t('sourcing.processingHint')}</p>
                    )}
                </div>
            ) : !file ? (
                <div
                    onDragEnter={handleDrag}
                    onDragLeave={handleDrag}
                    onDragOver={handleDrag}
                    onDrop={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragActive(false); pickFile(e.dataTransfer.files?.[0]); }}
                    role="button"
                    tabIndex={0}
                    aria-label={t('sourcing.uploadHint')}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInputRef.current?.click(); } }}
                    onClick={() => fileInputRef.current?.click()}
                    className={`group flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
                        isDragActive ? 'border-primary bg-accent' : 'border-border hover:border-primary/50 hover:bg-muted'
                    }`}
                >
                    <input
                        ref={fileInputRef}
                        type="file"
                        className="hidden"
                        accept={useAI ? AI_ACCEPT : '.xlsx,.xls'}
                        onChange={(e) => pickFile(e.target.files?.[0])}
                    />
                    <div className="mb-3 rounded-xl bg-primary/10 p-3">
                        <Upload className="h-6 w-6 text-primary" aria-hidden="true" />
                    </div>
                    <p className="mb-0.5 text-sm font-semibold text-foreground">{t('sourcing.uploadHint')}</p>
                    <p className="text-xs text-muted-foreground">{acceptText}</p>
                </div>
            ) : (
                <div className="flex flex-col gap-3 rounded-xl border border-border bg-muted/40 p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex min-w-0 items-center gap-3">
                        <div className="shrink-0 rounded-lg bg-primary/10 p-2">
                            <FileSpreadsheet className="h-5 w-5 text-primary" aria-hidden="true" />
                        </div>
                        <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-foreground">{file.name}</p>
                            <p className="text-xs text-muted-foreground">{(file.size / 1024).toFixed(1)} KB</p>
                        </div>
                    </div>
                    {/* shrink-0 + justify-end: the actions never get squeezed out of
                        view by a long filename; they wrap below it on narrow widths. */}
                    <div className="flex shrink-0 items-center justify-end gap-2">
                        {!isDispatching && (
                            <Button variant="ghost" size="icon" onClick={() => { setFile(null); setError(null); }} aria-label={t('common.delete')}>
                                <X className="h-4 w-4" />
                            </Button>
                        )}
                        <Button onClick={handleUpload} disabled={isDispatching} className="gap-1.5">
                            {isDispatching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                            {useAI ? t('aiImport.agree') : t('sourcing.uploadTitle')}
                        </Button>
                    </div>
                </div>
            )}

            {error && (
                <Alert variant="destructive">
                    <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                    <AlertDescription className="flex items-center justify-between gap-3">
                        <span className="min-w-0">{error}</span>
                        {canRetry && !isImporting && !isDispatching && lastFileRef.current && (
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={handleRetry}
                                className="h-7 shrink-0 gap-1.5 text-xs"
                            >
                                <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                                {t('common.retry')}
                            </Button>
                        )}
                    </AlertDescription>
                </Alert>
            )}
        </div>
    );
};
