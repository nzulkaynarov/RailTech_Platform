import React from 'react';
import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';
import { clsx } from 'clsx';
import { Button } from '@/components/ui/button';

/**
 * Compact language switcher (RU/EN toggle).
 * Designed to sit in the sidebar or header next to ThemeToggle.
 */
export const LanguageSwitcher: React.FC<{ className?: string }> = ({ className }) => {
  const { i18n, t } = useTranslation();
  const isRu = i18n.language?.startsWith('ru');

  const toggle = () => {
    i18n.changeLanguage(isRu ? 'en' : 'ru');
  };

  return (
    <Button
      type="button"
      variant="ghost"
      onClick={toggle}
      aria-label={isRu ? t('languageSwitcher.switchToEn') : t('languageSwitcher.switchToRu')}
      className={clsx(
        'flex items-center gap-1.5 h-auto',
        className,
      )}
    >
      <Globe size={14} />
      <span>{isRu ? t('languageSwitcher.labelEn') : t('languageSwitcher.labelRu')}</span>
    </Button>
  );
};
