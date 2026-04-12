import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';
import { PageShell } from './shared/PageShell';

export function MyDocumentsPage() {
  const { t } = useTranslation();

  return (
    <PageShell
      title={t('pages.documents.title')}
      description={t('pages.documents.description')}
      icon={<FileText className="h-5 w-5" />}
    />
  );
}

export default MyDocumentsPage;
