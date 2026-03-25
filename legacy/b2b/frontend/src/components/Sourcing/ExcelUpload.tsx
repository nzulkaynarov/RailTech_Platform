import React, { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileSpreadsheet, X, CheckCircle, Loader2 } from 'lucide-react';
import { crmApi } from '../../api/crmApi';
import { useTaskStore } from '../../store/taskStore';
import { clsx } from 'clsx';
import { Button } from '@/components/ui/button';

interface ExcelUploadProps {
    dealId: number;
    onUploadSuccess?: (taskId: string) => void;
}

export const ExcelUpload: React.FC<ExcelUploadProps> = ({ dealId, onUploadSuccess }) => {
    const { t } = useTranslation();
    const [file, setFile] = useState<File | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [isDragActive, setIsDragActive] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { addTask, tasks } = useTaskStore();

    const activeTaskId = Object.keys(tasks).find(id => tasks[id].status === 'PROGRESS' || tasks[id].status === 'PENDING');
    const activeTask = activeTaskId ? tasks[activeTaskId] : null;

    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setIsDragActive(true);
        } else {
            setIsDragActive(false);
        }
    };

    const validateFile = (file: File) => {
        const validTypes = [
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.ms-excel'
        ];
        if (!validTypes.includes(file.type)) {
            setError(t('sourcing.uploadError'));
            return false;
        }
        setError(null);
        return true;
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragActive(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            const droppedFile = e.dataTransfer.files[0];
            if (validateFile(droppedFile)) {
                setFile(droppedFile);
            }
        }
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            const selectedFile = e.target.files[0];
            if (validateFile(selectedFile)) {
                setFile(selectedFile);
            }
        }
    };

    const removeFile = () => {
        setFile(null);
        setError(null);
    };

    const handleUpload = async () => {
        if (!file) return;

        setIsUploading(true);
        setError(null);
        try {
            const result = await crmApi.importExcelToDeal(dealId, file);
            addTask(result.task_id, 'excel_import');

            setFile(null);
            setIsUploading(false);

            if (onUploadSuccess) {
                onUploadSuccess(result.task_id);
            }
        } catch (err: unknown) {
            const errorMessage = err instanceof Error ? err.message : t('sourcing.uploadError');
            setError(errorMessage);
            setIsUploading(false);
        }
    };

    return (
        <div className="w-full max-w-xl mx-auto p-5 bg-card rounded-xl border border-border shadow-sm">
            <h3 className="text-base font-bold text-foreground mb-4 flex items-center gap-2">
                <Upload className="w-5 h-5 text-primary" aria-hidden="true" />
                {t('sourcing.uploadTitle')}
            </h3>

            {!file ? (
                <div
                    onDragEnter={handleDrag}
                    onDragLeave={handleDrag}
                    onDragOver={handleDrag}
                    onDrop={handleDrop}
                    role="button"
                    tabIndex={0}
                    aria-label={t('sourcing.uploadHint')}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInputRef.current?.click(); } }}
                    className={clsx(
                        'relative group cursor-pointer transition-all',
                        'border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center text-center',
                        isDragActive
                            ? 'border-primary bg-accent'
                            : 'border-border dark:border-border hover:border-primary/50 hover:bg-muted dark:hover:bg-white/[0.02]'
                    )}
                    onClick={() => fileInputRef.current?.click()}
                >
                    <input
                        ref={fileInputRef}
                        type="file"
                        className="hidden"
                        accept=".xlsx,.xls"
                        onChange={handleFileChange}
                    />
                    <div className="bg-primary/10 p-3 rounded-xl mb-3 group-hover:scale-105 transition-transform">
                        <FileSpreadsheet className="w-7 h-7 text-primary" aria-hidden="true" />
                    </div>
                    <p className="text-sm font-semibold text-foreground mb-0.5">
                        {t('sourcing.uploadHint')}
                    </p>
                    <p className="text-xs text-muted-foreground">
                        .xlsx, .xls
                    </p>
                </div>
            ) : (
                <div className="bg-muted dark:bg-muted/50 border border-border rounded-xl p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="bg-emerald-500/10 p-2 rounded-lg">
                            <FileSpreadsheet className="w-5 h-5 text-emerald-500" aria-hidden="true" />
                        </div>
                        <div>
                            <p className="text-sm font-semibold text-foreground truncate max-w-[200px]">
                                {file.name}
                            </p>
                            <p className="text-xs text-muted-foreground">
                                {(file.size / 1024).toFixed(1)} KB
                            </p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {!isUploading && (
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={removeFile}
                                aria-label={t('common.delete')}
                            >
                                <X className="w-4 h-4" />
                            </Button>
                        )}
                        <Button
                            onClick={handleUpload}
                            disabled={isUploading}
                        >
                            {isUploading ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    {t('sourcing.processing')}
                                </>
                            ) : (
                                <>
                                    <CheckCircle className="w-4 h-4" />
                                    {t('sourcing.uploadTitle')}
                                </>
                            )}
                        </Button>
                    </div>
                </div>
            )}

            {activeTask && activeTask.status === 'PROGRESS' && activeTask.progress && (
                <div className="mt-4">
                    <div className="flex justify-between text-xs text-muted-foreground mb-1">
                        <span>{t('sourcing.processing')}</span>
                        <span>{activeTask.progress.current} / {activeTask.progress.total}</span>
                    </div>
                    <div className="w-full bg-muted dark:bg-muted h-1.5 rounded-full overflow-hidden">
                        <div
                            className="bg-primary h-full transition-all duration-500 ease-out rounded-full"
                            style={{ width: `${Math.round((activeTask.progress.current / activeTask.progress.total) * 100)}%` }}
                        />
                    </div>
                </div>
            )}

            {(error || (activeTask && activeTask.error)) && (
                <div className="mt-4 p-3 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-lg text-red-600 dark:text-red-400 text-sm" role="alert">
                    {error || activeTask?.error}
                </div>
            )}
        </div>
    );
};
