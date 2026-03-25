import React from 'react';
import { useTranslation } from 'react-i18next';
import { useTaskStore } from '../../store/taskStore';
import { Loader2, CheckCircle2, AlertCircle, X, FileSpreadsheet, Package } from 'lucide-react';
import { clsx } from 'clsx';
import { Button } from '@/components/ui/button';

export const GlobalTaskProgress: React.FC = () => {
    const { t } = useTranslation();
    const { activeTaskIds, tasks, removeTask } = useTaskStore();

    if (activeTaskIds.length === 0) return null;

    return (
        <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-3 w-80 pointer-events-none">
            {activeTaskIds.map((id) => {
                const task = tasks[id];
                if (!task) return null;

                const isProgress = task.status === 'PROGRESS';
                const isSuccess = task.status === 'SUCCESS';
                const isFailure = task.status === 'FAILURE';

                return (
                    <div
                        key={id}
                        className={clsx(
                            "pointer-events-auto bg-card border rounded-2xl p-4 shadow-2xl flex items-start gap-3 transition-all animate-in slide-in-from-right-full",
                            isFailure ? "border-red-500/20" : "border-border"
                        )}
                    >
                        <div className={clsx(
                            "w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-sm",
                            isSuccess ? "bg-emerald-50 text-emerald-600" :
                            isFailure ? "bg-red-50 text-red-600" : "bg-primary/10 text-primary"
                        )}>
                            {task.type === 'excel_import' ? <FileSpreadsheet className="w-5 h-5" /> : <Package className="w-5 h-5" />}
                        </div>

                        <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between mb-1">
                                <h5 className="text-xs font-black uppercase tracking-widest text-muted-foreground">
                                    {task.type === 'excel_import' ? t('task.excelImport') : t('task.catalogUpdate')}
                                </h5>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => removeTask(id)}
                                    className="p-1 h-auto w-auto hover:bg-muted rounded-md text-muted-foreground transition-colors"
                                >
                                    <X className="w-3 h-3" />
                                </Button>
                            </div>

                            <p className="text-xs font-bold text-foreground truncate mb-2">
                                {isSuccess ? t('task.success') : isFailure ? t('task.failure') : t('task.processing')}
                            </p>

                            {isProgress && task.progress && (
                                <div className="space-y-1.5">
                                    <div className="flex justify-between text-xs font-black text-muted-foreground uppercase tracking-tighter">
                                        <span>{t('task.progress')}</span>
                                        <span>{task.progress.current} / {task.progress.total}</span>
                                    </div>
                                    <div className="h-1 w-full bg-muted rounded-full overflow-hidden">
                                        <div
                                            className="h-full bg-primary transition-all duration-300 shadow-sm shadow-primary/20"
                                            style={{ width: `${Math.round((task.progress.current / task.progress.total) * 100)}%` }}
                                        />
                                    </div>
                                </div>
                            )}

                            {isSuccess && (
                                <div className="flex items-center gap-1.5 text-xs text-emerald-600 font-bold bg-emerald-50 dark:bg-emerald-500/10 px-2 py-0.5 rounded-full w-fit">
                                    <CheckCircle2 className="w-3 h-3" /> {t('task.completed')}
                                </div>
                            )}

                            {isFailure && (
                                <div className="flex items-center gap-1.5 text-xs text-red-600 font-bold bg-red-50 dark:bg-red-500/10 px-2 py-0.5 rounded-full w-fit">
                                    <AlertCircle className="w-3 h-3" /> {task.error || t('errors.unknown')}
                                </div>
                            )}

                            {!isSuccess && !isFailure && !isProgress && (
                                <div className="flex items-center gap-2 text-xs text-primary font-black italic">
                                    <Loader2 className="w-3 h-3 animate-spin" /> {t('task.initializing')}
                                </div>
                            )}
                        </div>
                    </div>
                );
            })}
        </div>
    );
};
