import { useTranslation } from 'react-i18next';
import { ClipboardList } from 'lucide-react';
import { PageShell } from './shared/PageShell';

export function PurchaseTemplatesPage() {
  const { t } = useTranslation();

  return (
    <PageShell
      title={t('purchaseTemplates.title')}
      description={t('purchaseTemplates.subtitle')}
      icon={<ClipboardList className="h-5 w-5" />}
    />
  );
}
