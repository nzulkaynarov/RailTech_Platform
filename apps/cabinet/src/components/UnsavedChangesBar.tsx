import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, RotateCcw, Save } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface UnsavedChangesBarProps {
  dirty: boolean;
  onSave: () => void;
  onReset: () => void;
  pending?: boolean;
  className?: string;
}

export function UnsavedChangesBar({
  dirty,
  onSave,
  onReset,
  pending = false,
  className,
}: UnsavedChangesBarProps) {
  const { t } = useTranslation();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        if (dirty && !pending) {
          onSave();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [dirty, pending, onSave]);

  if (!dirty) return null;

  return (
    <aside
      role="region"
      aria-label={t('common.unsavedChanges', { defaultValue: 'Несохранённые изменения' })}
      className={cn(
        'sticky top-3 z-30 mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-navy px-4 py-3 text-primary-foreground shadow-xl border border-navy/20 animate-in fade-in-0 slide-in-from-top-2 duration-200 ease-out',
        className,
      )}
    >
      <div className="flex items-center gap-2.5">
        <AlertCircle className="size-4 shrink-0 text-sand" aria-hidden="true" />
        <span className="text-xs font-medium">
          {t('common.unsavedChanges', { defaultValue: 'Есть несохранённые изменения' })}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="rounded-xl text-xs text-primary-foreground hover:bg-navy-hover hover:text-primary-foreground"
          onClick={onReset}
          disabled={pending}
        >
          <RotateCcw className="size-3.5" aria-hidden="true" />
          {t('common.reset', { defaultValue: 'Сбросить' })}
        </Button>

        <Button
          type="button"
          size="sm"
          className="rounded-xl bg-canvas text-navy hover:bg-ice-navy text-xs font-semibold shadow-xs"
          onClick={onSave}
          disabled={pending}
        >
          <Save className="size-3.5 text-navy" aria-hidden="true" />
          {t('common.saveCmdS', { defaultValue: 'Сохранить ⌘S' })}
        </Button>
      </div>
    </aside>
  );
}
