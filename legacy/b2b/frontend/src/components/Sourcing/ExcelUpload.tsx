import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileSpreadsheet, X, Loader2, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { crmApi } from '../../api/crmApi';
import { useTaskStore } from '../../store/taskStore';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Alert, AlertDescription } from '@/components/ui/alert';

interface ExcelUploadProps {
    dealId: number;
    /** Fires only when the import task COMPLETES (not on enqueue). */
    onUploadSuccess?: (taskId: string) => void;
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
    const [taskId, setTaskId] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { addTask, tasks } = useTaskStore();

    const task = taskId ? tasks[taskId] : null;
    const isImporting = !!task && (task.status === 'PENDING' || task.status === 'PROGRESS');

    // Success/failure are driven by the POLLED task status — not by enqueue. The
    // parent only learns the import is done once the items actually exist.
    useEffect(() => {
        if (!task) return;
        if (task.status === 'SUCCESS') {
            const finishedId = taskId;
            setTaskId(null);
            if (finishedId) onUploadSuccess?.(finishedId);
        } else if (task.status === 'FAILURE') {
            const message = task.error || t('sourcing.uploadError');
            setError(message);
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
            return false;
        }
        setError(null);
        return true;
    };

    const pickFile = (candidate?: File | null) => {
        if (candidate && validateFile(candidate)) setFile(candidate);
    };

    const handleUpload = async () => {
        if (!file) return;
        setIsDispatching(true);
        setError(null);
        try {
            const result = await crmApi.importExcelToDeal(dealId, file, useAI);
            addTask(result.task_id, 'excel_import');
            setTaskId(result.task_id); // success/failure handled by the polled status
            setFile(null);
        } catch (e) {
            const message = translateApiError(e);
            setError(message);
            toast.error(message);
        } finally {
            setIsDispatching(false);
        }
    };

    const acceptText = useAI ? t('aiImport.acceptedAi') : '.xlsx, .xls';

    return (
        <div className="space-y-3">
            {/* Importing — driven by polled task status */}
            {isImporting ? (
                <div className="rounded-xl border border-border p-5">
                    <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                        <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
                        {t('sourcing.processing')}
                    </div>
                    <Progress
                        value={task?.progress ? Math.round((task.progress.current / task.progress.total) * 100) : undefined}
                    />
                    {task?.progress && (
                        <p className="mt-1 text-right text-xs text-muted-foreground tabular-nums">
                            {task.progress.current} / {task.progress.total}
                        </p>
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
                <div className="flex items-center justify-between rounded-xl border border-border bg-muted/40 p-4">
                    <div className="flex min-w-0 items-center gap-3">
                        <div className="rounded-lg bg-primary/10 p-2">
                            <FileSpreadsheet className="h-5 w-5 text-primary" aria-hidden="true" />
                        </div>
                        <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-foreground">{file.name}</p>
                            <p className="text-xs text-muted-foreground">{(file.size / 1024).toFixed(1)} KB</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {!isDispatching && (
                            <Button variant="ghost" size="icon" onClick={() => { setFile(null); setError(null); }} aria-label={t('common.delete')}>
                                <X className="h-4 w-4" />
                            </Button>
                        )}
                        <Button onClick={handleUpload} disabled={isDispatching}>
                            {isDispatching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                            {useAI ? t('aiImport.agree') : t('sourcing.uploadTitle')}
                        </Button>
                    </div>
                </div>
            )}

            {error && (
                <Alert variant="destructive">
                    <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}
        </div>
    );
};
