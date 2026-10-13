import { useRef, useState, type DragEvent, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ImagePlus, Loader2, Trash2, Upload } from 'lucide-react';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

export interface ImageUploadProps {
    value?: string | null;
    onUpload: (file: File) => Promise<void> | void;
    onRemove?: () => Promise<void> | void;
    fallback?: string;
    maxSizeMB?: number;
    disabled?: boolean;
    shape?: 'circle' | 'square';
    className?: string;
    label?: string;
    description?: string;
}

const DEFAULT_MAX_SIZE_MB = 5;
const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/svg+xml'];

export function ImageUpload({
    value,
    onUpload,
    onRemove,
    fallback,
    maxSizeMB = DEFAULT_MAX_SIZE_MB,
    disabled,
    shape = 'square',
    className,
    label,
    description,
}: ImageUploadProps) {
    const { t } = useTranslation();
    const inputRef = useRef<HTMLInputElement | null>(null);
    const [isDragging, setIsDragging] = useState(false);
    const [isBusy, setIsBusy] = useState(false);

    const handleFile = async (file: File) => {
        if (!ACCEPTED_TYPES.includes(file.type)) {
            toast.error(t('fileUpload.errors.invalidImageType'));
            return;
        }
        if (file.size > maxSizeMB * 1024 * 1024) {
            toast.error(t('fileUpload.errors.tooLarge', { max: maxSizeMB }));
            return;
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
        const file = e.target.files?.[0];
        e.target.value = '';
        if (file) await handleFile(file);
    };

    const onDrop = async (e: DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const file = e.dataTransfer.files?.[0];
        if (file) await handleFile(file);
    };

    const onClickBrowse = () => inputRef.current?.click();

    const handleRemove = async () => {
        if (!onRemove) return;
        setIsBusy(true);
        try {
            await onRemove();
            toast.success(t('fileUpload.removed'));
        } catch {
            toast.error(t('fileUpload.errors.removeFailed'));
        } finally {
            setIsBusy(false);
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
                className={cn(
                    'flex items-center gap-4 rounded-lg border border-dashed p-4 transition-colors',
                    isDragging && 'border-primary bg-accent',
                    disabled && 'opacity-50',
                )}
            >
                <Avatar className={cn('h-20 w-20', shape === 'square' && 'rounded-md')}>
                    {value ? (
                        <AvatarImage src={value} alt="preview" />
                    ) : null}
                    <AvatarFallback className={cn(shape === 'square' && 'rounded-md')}>
                        {fallback ?? <ImagePlus className="size-6 text-muted-foreground" />}
                    </AvatarFallback>
                </Avatar>
                <div className="flex flex-1 flex-col gap-2">
                    {description && (
                        <p className="text-xs text-muted-foreground">{description}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                        {t('fileUpload.imageHelp', { max: maxSizeMB })}
                    </p>
                    <div className="flex gap-2">
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={onClickBrowse}
                            disabled={disabled || isBusy}
                        >
                            {isBusy ? (
                                <Loader2 className="size-4 animate-spin" />
                            ) : (
                                <Upload className="size-4" />
                            )}
                            {value ? t('fileUpload.replace') : t('fileUpload.upload')}
                        </Button>
                        {value && onRemove && (
                            <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                onClick={handleRemove}
                                disabled={disabled || isBusy}
                            >
                                <Trash2 className="size-4" />
                                {t('fileUpload.remove')}
                            </Button>
                        )}
                    </div>
                </div>
            </div>
            <input
                ref={inputRef}
                type="file"
                accept={ACCEPTED_TYPES.join(',')}
                className="hidden"
                onChange={onInputChange}
                disabled={disabled}
            />
        </div>
    );
}
