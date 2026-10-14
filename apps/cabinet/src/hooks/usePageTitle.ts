import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

/** `<title>` вкладки через i18n: «Раздел · RailTech Cabinet». */
export function usePageTitle(title: string): void {
  const { t } = useTranslation();
  const appName = t('app.name');
  useEffect(() => {
    document.title = title ? `${title} · ${appName}` : appName;
  }, [title, appName]);
}
