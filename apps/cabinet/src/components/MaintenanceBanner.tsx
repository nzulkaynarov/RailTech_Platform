import { useTranslation } from 'react-i18next';
import { TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useMaintenanceNotice } from '@/hooks/useMaintenanceNotice';

/**
 * Плашка планового обновления над шапкой (DECISIONS 2026-11-23): за 30 минут до начала — «Обновление кабинета в 19:15 —
 * работа прервётся на 2–3 минуты. Сохраните изменения.», во время работ — «Идёт обновление…». Срочное исправление
 * (`kind: urgent`) — то же место, другое слово. Скрывается на 10 минут, в последние 5 возвращается. Логика — `lib/maintenance.ts`.
 */
export function MaintenanceBanner() {
  const { t } = useTranslation();
  const { view, dismiss } = useMaintenanceNotice();
  if (!view) return null;
  const urgent = view.kind === 'urgent' ? 'Urgent' : '';
  const text =
    view.phase === 'soon'
      ? t(`maintenance.soon${urgent}`, {
          time: view.time,
          duration: t('maintenance.minutes', {
            count: view.to,
            range: view.from === view.to ? String(view.to) : `${view.from}–${view.to}`,
          }),
        })
      : t(`maintenance.running${urgent}`);
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-2.5 gap-y-2 border-b border-warning/40 bg-warning/10 px-4 py-2 text-sm text-foreground md:rounded-t-lg md:px-6"
    >
      <TriangleAlert className="size-4 shrink-0 text-warning" aria-hidden="true" />
      <span className="min-w-0 flex-1 basis-48">{text}</span>
      {view.dismissible ? (
        <Button variant="outline" size="sm" onClick={dismiss}>
          {t('maintenance.hide')}
        </Button>
      ) : null}
    </div>
  );
}
