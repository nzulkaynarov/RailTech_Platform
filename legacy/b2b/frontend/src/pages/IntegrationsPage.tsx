import { useTranslation } from 'react-i18next';
import { Plug } from 'lucide-react';
import { PageShell } from './shared/PageShell';

export function IntegrationsPage() {
  const { t } = useTranslation();

  return (
    <PageShell
      title={t('pages.integrations.title')}
      description={t('pages.integrations.description')}
      icon={<Plug className="h-5 w-5" />}
    />
  );
}

export default IntegrationsPage;
