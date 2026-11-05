import { useTranslation } from 'react-i18next';
import { BellRing } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useTelegramStep } from '@/onboarding/telegramStep';

/**
 * Плашка «Подключите Telegram — уведомления мгновенно» — вид шага «Подключить Telegram»: логика и состояния — в
 * `onboarding/telegramStep.ts`, здесь только отображение состояния `todo` (ADR-0023 п. 3; эталон — Slack и Intercom
 * «включите мобильные уведомления»). Не показывается в Telegram Mini App (там Telegram уже есть), если Telegram
 * привязан или подключить его нельзя (`available=false`), на самом Профиле и 14 дней после «Позже».
 * Плашка плавающая (fixed: над нижней навигацией телефона, в правом нижнем углу на компьютере) — она появляется, когда
 * пришёл статус, и не сдвигает уже показанное содержимое (CLS загрузки «Запросов» ≤ 0,01, CAB-FIX-3).
 */
export function TelegramBanner({ onProfile }: { onProfile: boolean }) {
  const { t } = useTranslation();
  const step = useTelegramStep({ enabled: !onProfile });

  if (onProfile || step.state !== 'todo') return null;

  return (
    <section
      aria-label={t('telegramBanner.label')}
      className="fixed inset-x-3 bottom-[calc(4.25rem+env(safe-area-inset-bottom))] z-30 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-background p-3.5 text-sm shadow-lg md:inset-x-auto md:right-6 md:bottom-6 md:w-96"
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <BellRing className="size-4 shrink-0 text-primary" aria-hidden="true" />
        <span className="font-medium text-primary">{t('telegramBanner.text')}</span>
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={step.connect}>
          {t('telegramBanner.connect')}
        </Button>
        <Button size="sm" variant="ghost" onClick={step.snooze}>
          {t('telegramBanner.later')}
        </Button>
      </div>
    </section>
  );
}
