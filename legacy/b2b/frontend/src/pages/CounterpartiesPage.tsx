import { useState } from 'react'; import { useTranslation } from 'react-i18next'; import { activeDateFnsLocale } from '@/lib/formatLocale'; import { formatDistanceToNow } from 'date-fns'; import { toast } from 'sonner'; import {   Users, Truck, Clock, History, CheckCircle2, AlertTriangle, XCircle, Info, Send, Loader2, } from 'lucide-react'; import { Card, CardContent } from '@/components/ui/card'; import { Badge } from '@/components/ui/badge'; import { Button } from '@/components/ui/button'; import { Label } from '@/components/ui/label'; import {   Select, SelectContent, SelectItem, SelectTrigger, SelectValue, } from '@/components/ui/select'; import {   Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, } from '@/components/ui/sheet'; import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable'; import { Toolbar, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';
import { useCurrencyStore } from '@/store/currencyStore';
import { useRelationships, useUpdateRelationship, useCompanyTimeline, useInviteContact } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { CreateOfflineClientDialog } from '@/components/CRM/CreateOfflineClientDialog';
import type {
  Relationship, RelationshipDirection, RelationshipStage, TimelineEntry,
} from '@/api/crmApi';
import { activityTitle, activityDetail } from '@/lib/activityText';

/* ─── CRM Phase B — «Книга контрагентов» ─────────────────────────────────────
 * ONE page for both directions of the relationship book: direction=CLIENT is
 * the seller's client book («Клиенты»), direction=SUPPLIER the buyer's supplier
 * book («Поставщики»). Rows are read-only rollups; the ONLY writes are the two
 * human-managed fields (stage verdict / account owner) via PATCH.
 */

// Stage/source are stable DB codes (Rule 2) — variants keyed by CODE, labels via t().
const STAGE_VARIANT: Record<RelationshipStage, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  PROSPECT: 'secondary',
  ACTIVE: 'default',
  DORMANT: 'outline',
  LOST: 'destructive',
};

const STAGE_CODES: RelationshipStage[] = ['PROSPECT', 'ACTIVE', 'DORMANT', 'LOST'];

// Same level→icon mapping as DealTimeline (duplicated locally on purpose — the
// deal feed stays untouched; this is the company-scoped variant of the feed).
const LEVEL_ICON: Record<TimelineEntry['level'], typeof Info> = {
  INFO: Info,
  SUCCESS: CheckCircle2,
  WARNING: AlertTriangle,
  ERROR: XCircle,
};

const LEVEL_CLASS: Record<TimelineEntry['level'], string> = {
  INFO: 'text-muted-foreground',
  SUCCESS: 'text-success',
  WARNING: 'text-warning',
  ERROR: 'text-destructive',
};

/** Company-scoped history feed for the counterparty card (CRM Phase A timeline API). */
function CompanyTimeline({ companyId }: { companyId: number }) {
  const { t, i18n } = useTranslation();
  const { data: entries, isLoading } = useCompanyTimeline(companyId);
  const dateLocale = activeDateFnsLocale();

  if (isLoading || !entries || entries.length === 0) {
    // Supplementary context — an empty/failed feed must not add noise to the card.
    return null;
  }

  return (
    <div className="space-y-3">
      <p className="flex items-center gap-2 text-sm font-medium">
        <History className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        {t('timeline.title')}
      </p>
      <ol className="relative border-s border-border ms-2 space-y-4">
        {entries.map((entry) => {
          const Icon = LEVEL_ICON[entry.level] ?? Info;
          const title = activityTitle(t, i18n, entry);
          const detail = activityDetail(t, i18n, entry);
          return (
            <li key={entry.id} className="ms-4">
              <span className="absolute -start-2 mt-1 flex h-4 w-4 items-center justify-center rounded-full bg-background">
                <Icon className={`h-3.5 w-3.5 ${LEVEL_CLASS[entry.level] ?? LEVEL_CLASS.INFO}`} />
              </span>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <p className="text-sm font-medium text-foreground">{title}</p>
                <time className="text-xs text-muted-foreground">
                  {formatDistanceToNow(new Date(entry.timestamp), { addSuffix: true, locale: dateLocale })}
                </time>
              </div>
              {detail && <p className="text-xs text-muted-foreground mt-0.5">{detail}</p>}
              {entry.user_name && <p className="text-xs text-muted-foreground/70 mt-0.5">{entry.user_name}</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

interface CounterpartiesPageProps {
  direction: RelationshipDirection;
}

export function CounterpartiesPage({ direction }: CounterpartiesPageProps) {
  const { t } = useTranslation();
  const { data: relationships, isLoading, isError, refetch } = useRelationships(direction);
  const updateMut = useUpdateRelationship();
  const inviteMut = useInviteContact();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const dateLocale = activeDateFnsLocale();

  const listParams = useListParams([] as const, { urlKey: 'counterparties', defaultOrdering: '-last_interaction_at' });
  const [selected, setSelected] = useState<Relationship | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const isClientBook = direction === 'CLIENT';
  const title = isClientBook ? t('counterparties.title.clients') : t('counterparties.title.suppliers');
  const description = isClientBook
    ? t('counterparties.description.clients')
    : t('counterparties.description.suppliers');

  const onStageChange = async (relationship: Relationship, stage: RelationshipStage) => {
    if (stage === relationship.stage) return;
    try {
      const updated = await updateMut.mutateAsync({ id: relationship.id, data: { stage } });
      setSelected(updated);
      toast.success(t('counterparties.stageUpdated'));
    } catch (err) {
      toast.error(translateApiError(err));
    }
  };

  const onInvite = async (contactId: number) => {
    try {
      await inviteMut.mutateAsync(contactId);
      toast.success(t('counterparties.inviteSent'));
    } catch (err) {
      toast.error(translateApiError(err));
    }
  };

  const innOf = (relationship: Relationship) =>
    relationship.counterparty.inn || relationship.counterparty.stated_inn || '';

  const columns: ResponsiveColumn<Relationship>[] = [
    {
      id: 'counterparty', header: t('counterparties.table.counterparty'), mobileTitle: true,
      cell: (relationship) => (
        <div className="flex flex-col gap-0.5">
          <span className="inline-flex items-center gap-2 font-medium">
            {relationship.counterparty.name}
            {!relationship.counterparty.is_registered && (
              <Badge variant="outline">{t('counterparties.offline')}</Badge>
            )}
          </span>
          {innOf(relationship) && (
            <span className="text-xs text-muted-foreground">
              {t('counterparties.inn')} {innOf(relationship)}
            </span>
          )}
        </div>
      ),
    },
    {
      id: 'stage', header: t('counterparties.table.stage'),
      cell: (relationship) => (
        <Badge variant={STAGE_VARIANT[relationship.stage]}>
          {t(`counterparties.stage.${relationship.stage}`)}
        </Badge>
      ),
    },
    {
      id: 'deals', sortKey: 'deals_count', header: t('counterparties.table.deals'), className: 'text-right',
      cell: (relationship) => (
        <span className="tabular-nums">
          {relationship.deals_count}
          <span className="text-muted-foreground"> / {relationship.won_count}</span>
        </span>
      ),
    },
    {
      id: 'gmv', sortKey: 'gmv', header: t('counterparties.table.gmv'), className: 'text-right',
      cell: (relationship) => (
        <span className="font-medium tabular-nums">
          {Number(relationship.gmv) > 0
            ? formatCurrency(Number(relationship.gmv))
            : <span className="text-muted-foreground">—</span>}
        </span>
      ),
    },
    {
      id: 'last_interaction', sortKey: 'last_interaction_at', header: t('counterparties.table.lastInteraction'),
      cell: (relationship) => (relationship.last_interaction_at
        ? (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" aria-hidden="true" />
            {formatDistanceToNow(new Date(relationship.last_interaction_at), { addSuffix: true, locale: dateLocale })}
          </span>
        )
        : <span className="text-muted-foreground">—</span>),
    },
    {
      id: 'owner', header: t('counterparties.table.owner'),
      cell: (relationship) => (relationship.owner_member_name
        ? <span>{relationship.owner_member_name}</span>
        : <span className="text-muted-foreground italic">{t('counterparties.table.ownerUnassigned')}</span>),
    },
  ];

  return (
    <PageShell
      title={title}
      description={description}
      icon={isClientBook ? <Users className="h-5 w-5" /> : <Truck className="h-5 w-5" />}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('counterparties.searchPlaceholder')}
        newLabel={isClientBook ? t('counterparties.newClient') : undefined}
        onNew={isClientBook ? () => setCreateOpen(true) : undefined}
      />
      <CreateOfflineClientDialog open={createOpen} onOpenChange={setCreateOpen} />

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(relationships ?? [], listParams, {
              searchFields: (relationship) => [
                relationship.counterparty.name,
                relationship.counterparty.inn,
                relationship.counterparty.stated_inn,
              ],
              sortAccessors: {
                deals_count: (relationship) => relationship.deals_count,
                gmv: (relationship) => Number(relationship.gmv) || 0,
                last_interaction_at: (relationship) => relationship.last_interaction_at ?? '',
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) {
              return (
                <EmptyState
                  icon={isClientBook ? <Users className="h-5 w-5" /> : <Truck className="h-5 w-5" />}
                  message={t('counterparties.emptyState')}
                  hint={isClientBook ? t('counterparties.emptyStateHintClients') : t('counterparties.emptyStateHintSuppliers')}
                  action={isClientBook
                    ? { label: t('counterparties.newClient'), onClick: () => setCreateOpen(true) }
                    : undefined}
                />
              );
            }
            return (
              <>
                <ResponsiveDataTable
                  columns={columns}
                  rows={pageItems}
                  getRowId={(relationship) => relationship.id}
                  onRowClick={setSelected}
                  sorting={{ ordering: listParams.ordering, onToggle: listParams.toggleOrdering }}
                />
                <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
              </>
            );
          })()}
        </CardContent>
      </Card>

      {selected && (
        <Sheet open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
          <SheetContent className="overflow-y-auto sm:max-w-lg">
            <SheetHeader>
              <SheetTitle>{selected.counterparty.name}</SheetTitle>
              <SheetDescription className="flex flex-wrap items-center gap-2">
                <Badge variant={STAGE_VARIANT[selected.stage]}>
                  {t(`counterparties.stage.${selected.stage}`)}
                </Badge>
                <Badge variant={selected.counterparty.is_registered ? 'secondary' : 'outline'}>
                  {selected.counterparty.is_registered
                    ? t('counterparties.registered')
                    : t('counterparties.offline')}
                </Badge>
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <Label>{t('counterparties.inn')}</Label>
                  <p className="text-muted-foreground">{innOf(selected) || '—'}</p>
                </div>
                <div>
                  <Label>{t('counterparties.detail.deals')}</Label>
                  <p className="tabular-nums">
                    {selected.deals_count}
                    <span className="text-muted-foreground"> / {selected.won_count}</span>
                  </p>
                </div>
                <div>
                  <Label>{t('counterparties.table.gmv')}</Label>
                  <p className="tabular-nums">
                    {Number(selected.gmv) > 0 ? formatCurrency(Number(selected.gmv)) : '—'}
                  </p>
                </div>
                <div>
                  <Label>{t('counterparties.detail.source')}</Label>
                  <p className="text-muted-foreground">{t(`counterparties.source.${selected.source}`)}</p>
                </div>
                <div>
                  <Label>{t('counterparties.detail.firstInteraction')}</Label>
                  <p className="text-muted-foreground">
                    {selected.first_interaction_at
                      ? formatDistanceToNow(new Date(selected.first_interaction_at), { addSuffix: true, locale: dateLocale })
                      : '—'}
                  </p>
                </div>
                <div>
                  <Label>{t('counterparties.detail.lastInteraction')}</Label>
                  <p className="text-muted-foreground">
                    {selected.last_interaction_at
                      ? formatDistanceToNow(new Date(selected.last_interaction_at), { addSuffix: true, locale: dateLocale })
                      : '—'}
                  </p>
                </div>
                <div>
                  <Label>{t('counterparties.table.owner')}</Label>
                  <p className="text-muted-foreground">
                    {selected.owner_member_name || t('counterparties.table.ownerUnassigned')}
                  </p>
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="relationship-stage">{t('counterparties.detail.stage')}</Label>
                <Select
                  value={selected.stage}
                  onValueChange={(value) => onStageChange(selected, value as RelationshipStage)}
                  disabled={updateMut.isPending}
                >
                  <SelectTrigger id="relationship-stage" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {STAGE_CODES.map((code) => (
                      <SelectItem key={code} value={code}>
                        {t(`counterparties.stage.${code}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {isClientBook && !selected.counterparty.is_registered && selected.counterparty.primary_contact_id && (
                <Button
                  variant="outline"
                  className="w-full"
                  disabled={inviteMut.isPending}
                  onClick={() => onInvite(selected.counterparty.primary_contact_id!)}
                >
                  {inviteMut.isPending
                    ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    : <Send className="h-4 w-4" aria-hidden="true" />}
                  {t('counterparties.invite')}
                </Button>
              )}

              <CompanyTimeline companyId={selected.counterparty.id} />
            </div>
          </SheetContent>
        </Sheet>
      )}
    </PageShell>
  );
}

export default CounterpartiesPage;
