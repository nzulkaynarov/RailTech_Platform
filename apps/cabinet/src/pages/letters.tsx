import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, Loader2, Mail } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import type { LetterDirection, PortalLetter } from '@/api/portal';
import { useLetters } from '@/api/queries';
import { DealLink } from '@/components/Details';
import { EmptyState, NoMatchState } from '@/components/EmptyState';
import { ListToolbar } from '@/components/list/ListToolbar';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ResponsiveList } from '@/components/ResponsiveList';
import { ToneBadge } from '@/components/StatusBadge';
import { Button } from '@/components/ui/button';
import { downloadLetter } from '@/lib/download';
import { formatDate } from '@/lib/format';
import type { StatusTone } from '@/lib/status';
import { toast } from '@/lib/toast';

/**
 * «Письма» (ЛИД-8, ADR-0026): официальная переписка компании с нами — наши исходящие (ИСХ) с файлом и квитанции о
 * регистрации её писем (ВХ) с номером, датой и ответом. Только своя компания; фильтр — направление, поиск — номер и тема.
 */

const DIRECTIONS: (LetterDirection | undefined)[] = [undefined, 'out', 'in'];

const STATE_TONE: Record<PortalLetter['state'], StatusTone> = {
  registered: 'info',
  answered: 'success',
  sent: 'neutral',
};

function LetterFileButton({ letter }: { letter: PortalLetter }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const download = async () => {
    setBusy(true);
    try {
      await downloadLetter(letter.id, `${letter.number.replace('/', '-')}.pdf`);
    } catch (error) {
      toast.error(t(apiErrorKey(error)));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      disabled={busy}
      onClick={() => void download()}
      aria-label={t('documents.downloadNamed', { name: letter.number })}
    >
      {busy ? <Loader2 className="motion-safe:animate-spin" aria-hidden="true" /> : <Download aria-hidden="true" />}
      {t('documents.download')}
    </Button>
  );
}

export function LettersPage() {
  const { t } = useTranslation();
  const [direction, setDirection] = useState<LetterDirection | undefined>(undefined);
  const [query, setQuery] = useState('');
  const q = query.trim();
  const letters = useLetters({ direction, q: q || undefined });

  return (
    <>
      <PageHeader title={t('pages.letters.title')} icon={Mail} />
      <ListToolbar
        filterLabel={t('pages.letters.filter')}
        options={DIRECTIONS.map((option) => ({
          value: option ?? '',
          label: option ? t(`pages.letters.direction.${option}`) : t('common.all'),
        }))}
        value={direction ?? ''}
        onChange={(next) => setDirection((next || undefined) as typeof direction)}
        search={{ value: query, onChange: setQuery, placeholder: t('pages.letters.searchPlaceholder'), label: t('pages.letters.searchLabel') }}
      />
      {letters.isPending ? (
        <ListSkeleton />
      ) : letters.isError ? (
        <ErrorState error={letters.error} onRetry={() => void letters.refetch()} />
      ) : letters.data.length === 0 ? (
        q || direction ? (
          <NoMatchState
            title={t('pages.letters.noMatchTitle')}
            text={t('pages.letters.noMatchText')}
            resetLabel={t('common.reset')}
            onReset={() => {
              setQuery('');
              setDirection(undefined);
            }}
          />
        ) : (
          <EmptyState icon={Mail} title={t('pages.letters.emptyTitle')} text={t('pages.letters.emptyText')} />
        )
      ) : (
        <ResponsiveList<PortalLetter>
          label={t('pages.letters.title')}
          rows={letters.data}
          getRowId={(row) => row.id}
          title={{
            header: t('pages.letters.columns.letter'),
            cell: (row) => (
              <span className="flex flex-col">
                <span className="font-medium">{row.subject}</span>
                <span className="font-mono text-xs text-muted-foreground" translate="no">
                  {row.number}
                </span>
              </span>
            ),
          }}
          columns={[
            {
              id: 'direction',
              header: t('pages.letters.columns.direction'),
              cell: (row) => t(`pages.letters.direction.${row.direction}`),
            },
            {
              id: 'date',
              header: t('pages.letters.columns.date'),
              cell: (row) => formatDate(row.date),
            },
            {
              id: 'state',
              header: t('pages.letters.columns.state'),
              cell: (row) => (
                <span className="flex flex-col gap-1">
                  <ToneBadge tone={STATE_TONE[row.state]}>{t(`pages.letters.state.${row.state}`)}</ToneBadge>
                  {row.reply_number ? (
                    <span className="text-xs text-muted-foreground">
                      {t(row.direction === 'in' ? 'pages.letters.answeredBy' : 'pages.letters.replyTo', {
                        number: row.reply_number,
                      })}
                    </span>
                  ) : null}
                </span>
              ),
            },
            {
              id: 'deal',
              header: t('pages.letters.columns.deal'),
              cell: (row) => <DealLink deal={row.deal} />,
            },
          ]}
          actions={{
            header: t('common.actions'),
            cell: (row) => (row.has_file ? <LetterFileButton letter={row} /> : null),
          }}
        />
      )}
    </>
  );
}
