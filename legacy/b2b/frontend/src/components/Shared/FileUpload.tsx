import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, Loader2, Trash2, Upload, Download } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

export interface UploadedFile {
    id: string | number;
    name: string;
    url?: string | null;
    uploaded_at?: string | null;
}

export interface FileUploadProps {
    files: UploadedFile[];
    onUpload: (file: File) => Promise<void> | void;
    onRemove?: (id: string | number) => Promise<void> | void;
    // Authenticated download (streams via an endpoint). Preferred over the raw
    // file.url, which 404s on prod (local storage, no MinIO).
    onDownload?: (id: string | number, name: string) => Promise<void> | void;
    disabled?: boolean;
    maxSizeMB?: number;
    accept?: string;
    className?: string;
    label?: string;
    description?: string;
    emptyText?: string;
}

const DEFAULT_MAX_SIZE_MB = 25;
const DEFAULT_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.txt,.png,.jpg,.jpeg,.webp';

export function FileUpload({
    files,
    onUpload,
    onRemove,
    onDownload,
    disabled,
    maxSizeMB = DEFAULT_MAX_SIZE_MB,
    accept = DEFAULT_ACCEPT,
    className,
    label,
    description,
    emptyText,
}: FileUploadProps) {
    const { t } = useTranslation();
    const inputRef = useRef<HTMLInputElement | null>(null);
    const [isDragging, setIsDragging] = useState(false);
    const [isBusy, setIsBusy] = useState(false);
    const [removingId, setRemovingId] = useState<string | number | null>(null);

    const handleFile = async (file: File) => {
        if (file.size > maxSizeMB * 1024 * 1024) {
            toast.error(t('fileUpload.errors.tooLarge', { max: maxSizeMB }));
            return;
        }
        // Validate against `accept` (extensions and/or MIME) — the browser's accept
        // attribute is only a hint and is bypassed by drag-and-drop. Backend re-validates
        // by magic bytes (authoritative); this is early client-side feedback.
        const allowed = accept.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
        if (allowed.length) {
            const ext = `.${(file.name.split('.').pop() || '').toLowerCase()}`;
            const mime = (file.type || '').toLowerCase();
            const ok = allowed.some((a) =>
                a.startsWith('.') ? a === ext
                : a.endsWith('/*') ? mime.startsWith(a.slice(0, -1))
                : a === mime,
            );
            if (!ok) {
                toast.error(t('fileUpload.errors.invalidType'));
                return;
            }
        }
        setIsBusy(true);
        try {
            await onUpload(file);
            toast.success(t('fileUpload.uploaded'));
        } catch {
            toast.error(t('fileUpload.errors.uploadFailed'));
        } finally {
            setIsBusy(false);
        }
    };

    const onInputChange = async (e: ChangeEvent<HTMLInputElement>) => {
        const fileList = e.target.files;
        e.target.value = '';
        if (!fileList) return;
        for (const file of Array.from(fileList)) {
            await handleFile(file);
        }
    };

    const onDrop = async (e: DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const fileList = e.dataTransfer.files;
        if (!fileList) return;
        for (const file of Array.from(fileList)) {
            await handleFile(file);
        }
    };

    const handleRemove = async (id: string | number) => {
        if (!onRemove) return;
        setRemovingId(id);
        try {
            await onRemove(id);
            toast.success(t('fileUpload.removed'));
        } catch {
            toast.error(t('fileUpload.errors.removeFailed'));
        } finally {
            setRemovingId(null);
        }
    };

    return (
        <div className={cn('flex flex-col gap-3', className)}>
            {label && <div className="text-sm font-medium">{label}</div>}
            <div
                onDragOver={e => {
                    e.preventDefault();
                    if (!disabled) setIsDragging(true);
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={onDrop}
                onClick={() => !disabled && inputRef.current?.click()}
                className={cn(
                    'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-6 text-center transition-colors',
                    isDragging && 'border-primary bg-accent',
                    disabled && 'pointer-events-none opacity-50',
                )}
            >
                {isBusy ? (
                    <Loader2 className="size-6 animate-spin text-muted-foreground" />
                ) : (
                    <Upload className="size-6 text-muted-foreground" />
                )}
                <p className="text-sm">{t('fileUpload.dragDrop')}</p>
                {description && (
                    <p className="text-xs text-muted-foreground">{description}</p>
                )}
                <p className="text-xs text-muted-foreground">
                    {t('fileUpload.maxSize', { max: maxSizeMB })}
                </p>
            </div>
            <input
                ref={inputRef}
                type="file"
                multiple
                accept={accept}
                className="hidden"
                onChange={onInputChange}
                disabled={disabled}
            />
            {files.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                    {emptyText ?? t('fileUpload.noFiles')}
                </p>
            ) : (
                <ul className="flex flex-col gap-2">
                    {files.map(file => (
                        <li
                            key={file.id}
                            className="flex items-center justify-between gap-3 rounded-md border bg-card p-3"
                        >
                            <div className="flex min-w-0 items-center gap-3">
                                <FileText className="size-5 shrink-0 text-muted-foreground" />
                                <div className="min-w-0">
                                    <div className="truncate text-sm font-medium">{file.name}</div>
                                    {file.uploaded_at && (
                                        <div className="text-xs text-muted-foreground">
                                            {new Date(file.uploaded_at).toLocaleString()}
                                        </div>
                                    )}
                                </div>
                            </div>
                            <div className="flex shrink-0 gap-1">
                                {onDownload ? (
                                    <Button
                                        type="button"
                                        size="icon-sm"
                                        variant="ghost"
                                        aria-label={t('fileUpload.download')}
                                        onClick={() => onDownload(file.id, file.name)}
                                    >
                                        <Download className="size-4" />
                                    </Button>
                                ) : file.url ? (
                                    <Button
                                        asChild
                                        type="button"
                                        size="icon-sm"
                                        variant="ghost"
                                        aria-label={t('fileUpload.download')}
                                    >
                                        <a href={file.url} target="_blank" rel="noreferrer">
                                            <Download className="size-4" />
                                        </a>
                                    </Button>
                                ) : null}
                                {onRemove && (
                                    <Button
                                        type="button"
                                        size="icon-sm"
                                        variant="ghost"
                                        onClick={() => handleRemove(file.id)}
                                        disabled={removingId === file.id}
                                        aria-label={t('fileUpload.remove')}
                                    >
                                        {removingId === file.id ? (
                                            <Loader2 className="size-4 animate-spin" />
                                        ) : (
                                            <Trash2 className="size-4 text-destructive" />
                                        )}
                                    </Button>
                                )}
                            </div>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
