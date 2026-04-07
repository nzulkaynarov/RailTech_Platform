import React, { useState, useRef } from 'react';
import { Upload, CheckCircle2, AlertCircle, Loader2, Database, Download, Zap } from 'lucide-react';
import { catalogApi } from '../../api/catalogApi';
import { useTaskStore } from '../../store/taskStore';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { Alert, AlertDescription } from '@/components/ui/alert';

interface ExcelUploadModalProps {
    isOpen: boolean;
    onClose: () => void;
}

export const ExcelUploadModal: React.FC<ExcelUploadModalProps> = ({ isOpen, onClose }) => {
    const [file, setFile] = useState<File | null>(null);
    const [localStatus, setLocalStatus] = useState<'idle' | 'uploading' | 'error'>('idle');
    const [errorMessage, setErrorMessage] = useState('');
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { addTask, tasks } = useTaskStore();

    const activeTaskId = Object.keys(tasks).find(id => tasks[id].type === 'catalog_import' && (tasks[id].status === 'PROGRESS' || tasks[id].status === 'PENDING' || tasks[id].status === 'SUCCESS'));
    const activeTask = activeTaskId ? tasks[activeTaskId] : null;

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            setFile(e.target.files[0]);
            setLocalStatus('idle');
        }
    };

    const handleUpload = async () => {
        if (!file) return;

        setLocalStatus('uploading');
        try {
            const { task_id } = await catalogApi.importExcel(file);
            addTask(task_id, 'catalog_import');
            setFile(null);
            setLocalStatus('idle');
        } catch (err: unknown) {
            setLocalStatus('error');
            const axiosErr = err as { response?: { data?: { error?: string } } };
            setErrorMessage(axiosErr.response?.data?.error || 'U_UPLOAD_FAILURE: STREAM_INTERRUPTED_OR_INVALID_DATA.');
        }
    };

    const progressValue = activeTask?.progress
        ? (activeTask.progress.current / activeTask.progress.total) * 100
        : 0;

    return (
        <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
            <DialogContent className="sm:max-w-md font-mono">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2 text-sm font-black uppercase tracking-tight">
                        <Database className="size-4 text-primary" />
                        DATA_INGESTION_PROTOCOL
                    </DialogTitle>
                    <DialogDescription className="text-xs font-bold uppercase tracking-widest">
                        BULK_IMPORT_MODULE_XLSX_CSV
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4">
                    {localStatus === 'idle' && !activeTask && (
                        <div
                            onClick={() => fileInputRef.current?.click()}
                            className="cursor-pointer rounded-sm border border-dashed border-border p-10 text-center transition-all hover:border-primary/50 hover:bg-muted/30"
                        >
                            <Input
                                ref={fileInputRef}
                                type="file"
                                onChange={handleFileChange}
                                className="hidden"
                                accept=".xlsx,.xls,.csv"
                            />
                            <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded bg-muted">
                                <Upload className="size-5 text-muted-foreground" />
                            </div>
                            <h3 className="text-xs font-black uppercase tracking-tight">
                                {file ? file.name : 'SELECT_SOURCE_FILE'}
                            </h3>
                            <p className="mt-1 text-xs font-bold uppercase tracking-widest text-muted-foreground">
                                DRAG_DROP_OR_KEYPATCH_ENTRY
                            </p>
                        </div>
                    )}

                    {(localStatus === 'uploading' || (activeTask && (activeTask.status === 'PROGRESS' || activeTask.status === 'PENDING'))) && (
                        <div className="space-y-6 py-10 text-center">
                            <div className="relative mx-auto flex size-12 items-center justify-center rounded border border-primary/20 bg-primary/5">
                                <Loader2 className="size-6 animate-spin text-primary" />
                            </div>
                            <div>
                                <h3 className="flex items-center justify-center gap-2 text-xs font-black uppercase tracking-widest">
                                    <Zap className="size-3.5 text-primary" />
                                    {localStatus === 'uploading' ? 'STREAMING_BINARY...' : 'PROCESSING_BUFFER...'}
                                </h3>
                                {activeTask?.progress && (
                                    <p className="mt-2 text-xs font-mono uppercase text-muted-foreground">
                                        RECORDS: {activeTask.progress.current.toString().padStart(4, '0')} / {activeTask.progress.total.toString().padStart(4, '0')}
                                    </p>
                                )}
                            </div>
                            {activeTask?.progress && (
                                <Progress value={progressValue} className="h-1" />
                            )}
                        </div>
                    )}

                    {activeTask?.status === 'SUCCESS' && (
                        <div className="animate-in fade-in py-10 text-center duration-500">
                            <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded border border-emerald-500/20 bg-emerald-500/5">
                                <CheckCircle2 className="size-6 text-emerald-500" />
                            </div>
                            <h3 className="text-xs font-black uppercase tracking-widest">COMMIT_SUCCESSFUL</h3>
                            <p className="mt-2 px-10 text-xs font-bold uppercase tracking-widest text-muted-foreground">
                                MASTER_REGISTRY_STATE_SYNCHRONIZED_WITH_NEW_NODES.
                            </p>
                        </div>
                    )}

                    {(localStatus === 'error' || activeTask?.status === 'FAILURE') && (
                        <div className="space-y-4 py-6 text-center">
                            <div className="mx-auto flex size-12 items-center justify-center rounded border border-destructive/20 bg-destructive/5">
                                <AlertCircle className="size-6 text-destructive" />
                            </div>
                            <Alert variant="destructive">
                                <AlertCircle className="size-4" />
                                <AlertDescription>
                                    {errorMessage || activeTask?.error || 'Unknown error'}
                                </AlertDescription>
                            </Alert>
                            <Button
                                variant="link"
                                onClick={() => setLocalStatus('idle')}
                                className="text-xs font-black uppercase tracking-widest"
                            >
                                RE_INITIALIZE_STREAM
                            </Button>
                        </div>
                    )}
                </div>

                <DialogFooter className="flex-col gap-2 sm:flex-col">
                    {localStatus === 'idle' && !activeTask && (
                        <Button
                            disabled={!file}
                            onClick={handleUpload}
                            className="w-full text-xs font-black uppercase tracking-widest"
                        >
                            <Upload className="size-3.5" />
                            START_UPLOAD_SEQUENCE
                        </Button>
                    )}
                    <div className="flex gap-2">
                        <Button
                            variant="outline"
                            onClick={() => catalogApi.exportTemplate()}
                            className="flex-1 text-xs font-black uppercase tracking-widest"
                            size="sm"
                        >
                            <Download className="size-3" />
                            TEMPLATE_XLSX
                        </Button>
                        <Button
                            variant="outline"
                            disabled={localStatus === 'uploading' || activeTask?.status === 'PROGRESS'}
                            onClick={onClose}
                            className="flex-1 text-xs font-black uppercase tracking-widest hover:text-destructive"
                            size="sm"
                        >
                            TERMINATE
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
