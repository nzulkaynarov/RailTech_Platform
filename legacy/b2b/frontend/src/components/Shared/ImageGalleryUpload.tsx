import { useRef, useState, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Star, Trash2, Upload } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';

export interface GalleryImage {
    id: number;
    url: string | null;
    is_main?: boolean;
    alt_text?: string;
}

export interface ImageGalleryUploadProps {
    images: GalleryImage[];
    onUpload: (file: File, isMain: boolean) => Promise<void> | void;
    onRemove?: (id: number) => Promise<void> | void;
    onSetMain?: (id: number) => Promise<void> | void;
    disabled?: boolean;
    maxSizeMB?: number;
    className?: string;
    label?: string;
}

const ACCEPTED = ['image/png', 'image/jpeg', 'image/webp'];

export function ImageGalleryUpload({
    images,
    onUpload,
    onRemove,
    onSetMain,
    disabled,
    maxSizeMB = 10,
    className,
    label,
}: ImageGalleryUploadProps) {
    const { t } = useTranslation();
    const inputRef = useRef<HTMLInputElement | null>(null);
    const [isBusy, setIsBusy] = useState(false);
    const [removingId, setRemovingId] = useState<number | null>(null);
    const [pendingRemoval, setPendingRemoval] = useState<number | null>(null);

    const handleFile = async (file: File) => {
        if (!ACCEPTED.includes(file.type)) {
            toast.error(t('fileUpload.errors.invalidImageType'));
            return;
        }
        if (file.size > maxSizeMB * 1024 * 1024) {
            toast.error(t('fileUpload.errors.tooLarge', { max: maxSizeMB }));
            return;
        }
        setIsBusy(true);
        try {
            const isMain = images.length === 0;
            await onUpload(file, isMain);
            toast.success(t('fileUpload.uploaded'));
        } catch {
            toast.error(t('fileUpload.errors.uploadFailed'));
        } finally {
            setIsBusy(false);
        }
    };

    const onInputChange = async (e: ChangeEvent<HTMLInputElement>) => {
        // `e.target.files` — ЖИВОЙ FileList, привязанный к полю: очистка `value` опустошает его.
        // Снимок делаем ДО сброса, иначе цикл идёт по пустому списку и «выбрать файл» молча не
        // делает ничего — ни запроса, ни ошибки (найдено прогоном глазами 19-08). Сам сброс нужен,
        // чтобы повторный выбор ТОГО ЖЕ файла снова дал событие change.
        const files = e.target.files ? Array.from(e.target.files) : [];
        e.target.value = '';
        for (const file of files) await handleFile(file);
    };

    const handleRemove = async (id: number) => {
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
            <ConfirmActionDialog
                open={pendingRemoval !== null}
                onOpenChange={(open) => !open && setPendingRemoval(null)}
                title={t('imageGallery.removeConfirmTitle')}
                description={t('imageGallery.removeConfirmDescription')}
                variant="destructive"
                confirmLabel={t('common.delete')}
                onConfirm={async () => {
                    const target = pendingRemoval;
                    setPendingRemoval(null);
                    if (target != null) await handleRemove(target);
                }}
            />
            {label && <div className="text-sm font-medium">{label}</div>}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
                {images.map(img => (
                    <div
                        key={img.id}
                        className={cn(
                            'group relative aspect-square overflow-hidden rounded-md border bg-muted',
                            img.is_main && 'ring-2 ring-primary',
                        )}
                    >
                        {img.url ? (
                            <img
                                src={img.url}
                                alt={img.alt_text ?? ''}
                                className="h-full w-full object-cover"
                            />
                        ) : (
                            <div className="flex h-full w-full items-center justify-center text-xs text-muted-foreground">
                                —
                            </div>
                        )}
                        {img.is_main && (
                            <div className="absolute left-1 top-1 inline-flex items-center gap-1 rounded bg-primary px-1.5 py-0.5 text-xs text-primary-foreground">
                                <Star className="size-3" />
                                {t('fileUpload.main')}
                            </div>
                        )}
                        <div className="absolute inset-0 flex items-end justify-end gap-1 bg-gradient-to-t from-black/50 to-transparent p-1 opacity-0 transition-opacity group-hover:opacity-100">
                            {!img.is_main && onSetMain && (
                                <Button
                                    type="button"
                                    size="icon-sm"
                                    variant="secondary"
                                    onClick={() => onSetMain(img.id)}
                                    aria-label={t('fileUpload.setMain')}
                                >
                                    <Star className="size-4" />
                                </Button>
                            )}
                            {/* Удаление изображения необратимо, а кнопка живёт поверх самой
                                картинки — попасть по ней случайно особенно легко (аудит UI, U4). */}
                            {onRemove && (
                                <Button
                                    type="button"
                                    size="icon-sm"
                                    variant="destructive"
                                    onClick={() => setPendingRemoval(img.id)}
                                    disabled={removingId === img.id}
                                    aria-label={t('fileUpload.remove')}
                                >
                                    {removingId === img.id ? (
                                        <Loader2 className="size-4 animate-spin" />
                                    ) : (
                                        <Trash2 className="size-4" />
                                    )}
                                </Button>
                            )}
                        </div>
                    </div>
                ))}
                <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    disabled={disabled || isBusy}
                    className={cn(
                        'flex aspect-square flex-col items-center justify-center gap-1 rounded-md border border-dashed text-muted-foreground transition-colors hover:border-primary hover:bg-accent',
                        (disabled || isBusy) && 'opacity-50',
                    )}
                >
                    {isBusy ? (
                        <Loader2 className="size-5 animate-spin" />
                    ) : (
                        <Upload className="size-5" />
                    )}
                    <span className="text-xs">{t('fileUpload.addImage')}</span>
                </button>
            </div>
            <input
                ref={inputRef}
                type="file"
                multiple
                accept={ACCEPTED.join(',')}
                className="hidden"
                onChange={onInputChange}
                disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
                {t('fileUpload.imageHelp', { max: maxSizeMB })}
            </p>
        </div>
    );
}
