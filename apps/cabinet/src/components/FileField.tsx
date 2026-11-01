import { useId, useRef, useState, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Paperclip, Upload, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { formatFileSize } from '@/lib/format';
import { cn } from '@/lib/utils';

/**
 * Поле файла кабинета вместо системного `input type="file"` («Choose File / No file chosen» на языке браузера, B-CABFIX-1,
 * образец — Платформа `shared/ui/FileField`, UX-2a): кнопка «Выбрать файл», выбранный файл с размером и «Убрать»,
 * перетаскивание файла на поле. Системное поле скрыто, но остаётся целью `<Label htmlFor={id}>` — подпись и тесты
 * (`getByLabelText(...)` + `upload`) ведут к нему. Проверку типа и размера делает экран (`lib/upload.ts`): поле только
 * отдаёт выбранный `File` (или `null` после «Убрать»).
 */
export function FileField({
  id,
  value,
  onChange,
  accept,
  disabled,
  invalid,
  describedBy,
}: {
  id: string;
  value: File | null;
  onChange: (file: File | null) => void;
  accept?: string;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const hintId = useId();
  const [dragging, setDragging] = useState(false);
  const described = [describedBy, hintId].filter(Boolean).join(' ');

  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    const file = event.dataTransfer.files[0];
    if (file) onChange(file);
  };

  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border border-dashed p-3',
        dragging ? 'border-primary bg-accent' : 'border-border',
        invalid ? 'border-destructive' : null,
      )}
      onDragOver={(event) => {
        if (disabled) return;
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={drop}
    >
      {/* Системное поле — только за своей кнопкой (eslint railtech/no-native-fields разрешает его здесь) */}
      <input
        ref={input}
        id={id}
        type="file"
        className="sr-only"
        tabIndex={-1}
        accept={accept}
        disabled={disabled}
        aria-describedby={described}
        aria-invalid={invalid || undefined}
        onChange={(event) => {
          const file = event.target.files?.[0];
          // тот же файл можно выбрать ещё раз (после «Убрать» или ошибки)
          event.target.value = '';
          if (file) onChange(file);
        }}
      />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Button type="button" variant="outline" size="sm" disabled={disabled} aria-describedby={described} onClick={() => input.current?.click()}>
          <Upload aria-hidden="true" />
          {value ? t('common.file.replace') : t('common.file.choose')}
        </Button>
        <span id={hintId} className="text-xs text-muted-foreground">
          {t('common.file.drop')}
        </span>
      </div>
      {value ? (
        <p className="flex min-w-0 items-center gap-2 text-sm">
          <Paperclip className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="min-w-0 truncate font-medium">{value.name}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{formatFileSize(value.size)}</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto shrink-0"
            disabled={disabled}
            aria-label={t('common.file.removeNamed', { name: value.name })}
            onClick={() => onChange(null)}
          >
            <X aria-hidden="true" />
            {t('common.file.remove')}
          </Button>
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">{t('common.file.none')}</p>
      )}
    </div>
  );
}
