import React from 'react';
import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';
import { clsx } from 'clsx';

/**
 * Compact language switcher (RU/EN toggle).
 * Designed to sit in the sidebar or header next to ThemeToggle.
 */
export const LanguageSwitcher: React.FC<{ className?: string }> = ({ className }) => {
  const { i18n } = useTranslation();
  const isRu = i18n.language?.startsWith('ru');

  const toggle = () => {
    i18n.changeLanguage(isRu ? 'en' : 'ru');
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isRu ? 'Switch to English' : 'Переключить на русский'}
      className={clsx(
        'flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-semibold transition-colors',
        'text-muted-foreground hover:text-foreground hover:bg-muted',
        'dark:text-muted-foreground dark:hover:text-white dark:hover:bg-muted',
        'focus-ring',
        className,
      )}
    >
      <Globe size={14} />
      <span>{isRu ? 'EN' : 'РУ'}</span>
    </button>
  );
};
