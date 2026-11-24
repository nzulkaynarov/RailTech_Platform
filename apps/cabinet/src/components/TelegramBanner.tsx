import { useTranslation } from 'react-i18next';
import { BellRing } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useTelegramStep } from '@/onboarding/telegramStep';

/**
 * Строка «Подключите Telegram — уведомления мгновенно» — вид шага «Подключить Telegram»: логика и состояния — в
 * `onboarding/telegramStep.ts`, здесь только отображение состояния `todo` (ADR-0023 п. 3). Живёт один раз, в шторке
 * уведомлений (колокольчик), сверху ленты, и ничего не перекрывает; чек-лист «Первые шаги» на домашних экранах несёт тот же
 * шаг. Не показывается в Telegram Mini App (там Telegram уже есть), если Telegram привязан или подключить его нельзя
 * (`available=false`), и 14 дней после «Позже» (в этом браузере).
 */
export function TelegramBanner({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  const step = useTelegramStep();

  if (step.state !== 'todo') return null;

  return (
    <section
      aria-label={t('telegramBanner.label')}
      className="mb-3 flex flex-wrap items-center justify-between gap-x-2 gap-y-1 rounded-lg border border-border bg-accent/60 py-2 pr-1.5 pl-3 text-sm"
    >
      <div className="flex min-w-0 basis-48 flex-1 items-center gap-2">
        <BellRing className="size-4 shrink-0 text-primary" aria-hidden="true" />
        <span className="min-w-0 font-medium text-primary">{t('telegramBanner.text')}</span>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button
          size="sm"
          onClick={() => {
            onNavigate?.();
            step.connect();
          }}
        >
          {t('telegramBanner.connect')}
        </Button>
        <Button size="sm" variant="ghost" onClick={step.snooze}>
          {t('telegramBanner.later')}
        </Button>
      </div>
    </section>
  );
}
