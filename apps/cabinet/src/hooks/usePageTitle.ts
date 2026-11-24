import { useEffect } from 'react';
import { useAppName } from '@/i18n/operator';

/** `<title>` вкладки через i18n: «Раздел · Кабинет <оператор>» (название — из настроек, задача «Н3a2»). */
export function usePageTitle(title: string): void {
  const appName = useAppName();
  useEffect(() => {
    document.title = title ? `${title} · ${appName}` : appName;
  }, [title, appName]);
}
