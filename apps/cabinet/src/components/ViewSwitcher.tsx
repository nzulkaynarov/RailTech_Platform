import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Columns3, List, FileText } from 'lucide-react';

import { cn } from '@/lib/utils';

export type ViewMode = 'kanban' | 'list' | 'documents';

export interface ViewSwitcherProps {
  currentView?: ViewMode;
  onViewChange?: (view: ViewMode) => void;
  showDocumentsTab?: boolean;
  documentsCount?: number;
  className?: string;
}

export function ViewSwitcher({
  currentView,
  onViewChange,
  showDocumentsTab = true,
  documentsCount,
  className,
}: ViewSwitcherProps) {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeView: ViewMode = currentView || (searchParams.get('view') as ViewMode) || 'kanban';

  const setView = (view: ViewMode) => {
    if (onViewChange) {
      onViewChange(view);
    } else {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('view', view);
          return next;
        },
        { replace: true },
      );
    }
  };

  return (
    <div
      role="tablist"
      aria-label={t('views.switcherLabel', { defaultValue: 'Переключатель представлений' })}
      className={cn(
        'inline-flex items-center gap-1 rounded-xl border border-hairline bg-alabaster p-1 text-xs',
        className,
      )}
    >
      <button
        type="button"
        role="tab"
        aria-selected={activeView === 'kanban'}
        onClick={() => setView('kanban')}
        className={cn(
          'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring',
          activeView === 'kanban'
            ? 'bg-canvas font-semibold text-navy shadow-2xs'
            : 'text-muted-foreground hover:text-charcoal',
        )}
      >
        <Columns3 className="size-3.5" aria-hidden="true" />
        <span>{t('views.kanban', { defaultValue: 'Канбан этапов' })}</span>
      </button>

      <button
        type="button"
        role="tab"
        aria-selected={activeView === 'list'}
        onClick={() => setView('list')}
        className={cn(
          'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring',
          activeView === 'list'
            ? 'bg-canvas font-semibold text-navy shadow-2xs'
            : 'text-muted-foreground hover:text-charcoal',
        )}
      >
        <List className="size-3.5" aria-hidden="true" />
        <span>{t('views.list', { defaultValue: 'Список' })}</span>
      </button>

      {showDocumentsTab && (
        <button
          type="button"
          role="tab"
          aria-selected={activeView === 'documents'}
          onClick={() => setView('documents')}
          className={cn(
            'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring',
            activeView === 'documents'
              ? 'bg-canvas font-semibold text-navy shadow-2xs'
              : 'text-muted-foreground hover:text-charcoal',
          )}
        >
          <FileText className="size-3.5" aria-hidden="true" />
          <span>{t('views.documents', { defaultValue: 'Документы' })}</span>
          {typeof documentsCount === 'number' && (
            <span className="ml-0.5 rounded-full bg-ice-navy px-1.5 py-0.2 font-mono text-xs text-navy">
              {documentsCount}
            </span>
          )}
        </button>
      )}
    </div>
  );
}
