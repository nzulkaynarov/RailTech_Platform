import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';
import { usePageStats } from '@/hooks/usePageStats';
import { PageShell } from './shared/PageShell';

export function SourcingMatchPage() {
  const { t } = useTranslation();
  const { data: ps } = usePageStats();
  const s = ps?.sourcing_match;
  return (
    <PageShell
      title={t('pages.sourcingMatch.title')}
      description={t('pages.sourcingMatch.description')}
      icon={<Search className="h-5 w-5" />}
      stats={[
        { label: t('pages.sourcingMatch.stats.unrecognized'), value: String(s?.unrecognized ?? '—') },
        { label: t('pages.sourcingMatch.stats.matches'), value: String(s?.matches ?? '—') },
        { label: t('pages.sourcingMatch.stats.needReview'), value: String(s?.need_review ?? '—') },
        { label: t('pages.sourcingMatch.stats.accuracy'), value: s?.accuracy ?? '—' },
      ]}
    />
  );
}

export default SourcingMatchPage;
