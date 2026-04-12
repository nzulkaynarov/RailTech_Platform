import { useTranslation } from 'react-i18next';
import { Factory } from 'lucide-react';
import { PageShell } from './shared/PageShell';

export function ProductionOrdersPage() {
  const { t } = useTranslation();

  return (
    <PageShell
      title={t('pages.productionOrders.title')}
      description={t('pages.productionOrders.description')}
      icon={<Factory className="h-5 w-5" />}
    />
  );
}

export default ProductionOrdersPage;
