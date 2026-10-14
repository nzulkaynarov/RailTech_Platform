import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { SearchX } from 'lucide-react';

import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t('common.notFoundTitle')} />
      <EmptyState icon={SearchX} title={t('common.notFoundTitle')} text={t('common.notFoundText')}>
        <Button asChild variant="outline">
          <Link to="/">{t('common.home')}</Link>
        </Button>
      </EmptyState>
    </>
  );
}
