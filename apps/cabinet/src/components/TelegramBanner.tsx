import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BellRing } from 'lucide-react';

import { useTelegramStatus } from '@/api/queries';
import { Button } from '@/components/ui/button';
import { bannerSnoozed, snoozeBanner } from '@/lib/telegramBanner';
import { useAppMode } from '@/session/mode';

/** Состояние перехода с плашки: Профиль сразу выпускает ссылку привязки. */
export interface ConnectTelegramState {
  connectTelegram: true;
}

/**
 * Плашка «Подключите Telegram — уведомления мгновенно» над содержимым кабинета (ADR-0023 п. 3; эталон — Slack и
 * Intercom «включите мобильные уведомления»). Не показывается в Telegram Mini App (там Telegram уже есть), если Telegram
 * привязан или подключить его нельзя (`available=false`), на самом Профиле и 14 дней после «Позже».
 * Плашка плавающая (fixed: над нижней навигацией телефона, в правом нижнем углу на компьютере) — она появляется, когда
 * пришёл статус, и не сдвигает уже показанное содержимое (CLS загрузки «Запросов» ≤ 0,01, CAB-FIX-3).
 */
export function TelegramBanner({ onProfile }: { onProfile: boolean }) {
  const { t } = useTranslation();
  const mode = useAppMode();
  const navigate = useNavigate();
  const [hidden, setHidden] = useState(() => bannerSnoozed(Date.now()));
  const show = mode === 'web' && !hidden && !onProfile;
  const status = useTelegramStatus({ enabled: show });

  if (!show || !status.data || status.data.linked || !status.data.available) return null;

  const later = () => {
    snoozeBanner(Date.now());
    setHidden(true);
  };
  const connect = () => {
    const state: ConnectTelegramState = { connectTelegram: true };
    navigate({ pathname: '/profile', hash: '#notifications' }, { state });
  };

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
        <Button size="sm" onClick={connect}>
          {t('telegramBanner.connect')}
        </Button>
        <Button size="sm" variant="ghost" onClick={later}>
          {t('telegramBanner.later')}
        </Button>
      </div>
    </section>
  );
}
