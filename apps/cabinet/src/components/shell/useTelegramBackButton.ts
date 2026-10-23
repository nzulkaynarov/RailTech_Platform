import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { isSectionRoot } from '@/app/nav';
import { useAppMode } from '@/session/mode';
import { getTelegramWebApp } from '@/telegram/webapp';

/**
 * Mini App: системная кнопка «Назад» Telegram на вложенных экранах вместо своей (без дублирования
 * кнопок Telegram, CONVENTIONS.md §4). Первый экран после deep-link (`start_param`) ведёт к разделам.
 */
export function useTelegramBackButton(): void {
  const mode = useAppMode();
  const { pathname, key } = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const backButton = getTelegramWebApp()?.BackButton;
    if (mode !== 'miniapp' || !backButton) return;
    if (isSectionRoot(pathname)) {
      backButton.hide();
      return;
    }
    const goBack = () => {
      if (key === 'default') navigate('/requests', { replace: true });
      else navigate(-1);
    };
    backButton.onClick(goBack);
    backButton.show();
    return () => backButton.offClick(goBack);
  }, [mode, pathname, key, navigate]);
}
