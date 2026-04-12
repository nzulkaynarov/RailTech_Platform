import { useTranslation } from 'react-i18next';
import { CalendarDays } from 'lucide-react';
import { PageShell } from './shared/PageShell';

export function ProductionSchedulePage() {
  const { t } = useTranslation();

  return (
    <PageShell
      title={t('pages.productionSchedule.title')}
      description={t('pages.productionSchedule.description')}
      icon={<CalendarDays className="h-5 w-5" />}
    />
  );
}

export default ProductionSchedulePage;
