import { useTranslation } from 'react-i18next';
import { Truck } from 'lucide-react';
import { PageShell } from './shared/PageShell';

export function LogisticsPage() {
  const { t } = useTranslation();

  return (
    <PageShell
      title={t('pages.logistics.title')}
      description={t('pages.logistics.description')}
      icon={<Truck className="h-5 w-5" />}
    />
  );
}

export default LogisticsPage;
