import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { formatDistanceToNow } from 'date-fns';
import { Users, History, CheckCircle2, AlertTriangle, XCircle, Info, Mail, Phone, Send, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { activeDateFnsLocale } from '@/lib/formatLocale';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import { Toolbar, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';
import { useContacts, useCompanyTimeline, useInviteContact } from '@/hooks/useCRM';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { translateApiError } from '@/lib/apiError';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { CreateOfflineClientDialog } from '@/components/CRM/CreateOfflineClientDialog';
import type { Contact, TimelineEntry } from '@/api/crmApi';
import { groupContactsByCompany, type ClientRow } from '@/lib/clientBook';
import { activityTitle, activityDetail } from '@/lib/activityText';

/* ─── Книга клиентов бэк-офиса («Клиенты») ───────────────────────────────────
 * С M1-ERP-02 волна 3 книга строится по контактам `accounts/contacts/` (компании, заведённые
 * сотрудниками своей компании, и их контакты). Стадии, роллапы и ответственный «рёбер»
 * `CounterpartyRelationship` удалены вместе с моделью; карточка клиента — контакты и история
 * компании. Полный реестр контрагентов (клиент / поставщик / субподрядчик) — `parties`, M1-ERP-03.
 */

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

/** История компании в карточке клиента (общий таймлайн CRM Phase A). */
function CompanyTimeline({ companyId }: { companyId: number }) {
  const { t, i18n } = useTranslation();
  const { data: entries, isLoading } = useCompanyTimeline(companyId);
  const dateLocale = activeDateFnsLocale();

  if (isLoading || !entries || entries.length === 0) return null;

  return (
    <div className="space-y-3">
      <p className="flex items-center gap-2 text-sm font-medium">
        <History className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        {t('timeline.title')}
      </p>
      <ol className="relative border-s border-border ms-2 space-y-4">
        {entries.map((entry) => {
          const Icon = LEVEL_ICON[entry.level] ?? Info;
          const detail = activityDetail(t, i18n, entry);
          return (
            <li key={entry.id} className="ms-4">
              <span className="absolute -start-2 mt-1 flex h-4 w-4 items-center justify-center rounded-full bg-background">
                <Icon className={`h-3.5 w-3.5 ${LEVEL_CLASS[entry.level] ?? LEVEL_CLASS.INFO}`} />
              </span>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <p className="text-sm font-medium text-foreground">{activityTitle(t, i18n, entry)}</p>
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

function ContactLine({ contact }: { contact: Contact }) {
  const { t } = useTranslation();
  const dateLocale = activeDateFnsLocale();

  return (
    <div className="flex flex-col gap-0.5 text-sm">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium">
          {contact.name}
          {contact.position && <span className="font-normal text-muted-foreground"> · {contact.position}</span>}
        </span>
        {contact.can_act !== undefined && (
          <Badge variant={contact.can_act ? 'secondary' : 'outline'} className="text-xs px-1.5 py-0 h-4">
            {contact.can_act ? t('counterparties.detail.canAct') : t('counterparties.detail.readOnly')}
          </Badge>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        {contact.phone && (
          <span className="inline-flex items-center gap-1">
            <Phone className="h-3 w-3" aria-hidden="true" />
            {contact.phone}
          </span>
        )}
        {contact.email && (
          <span className="inline-flex items-center gap-1">
            <Mail className="h-3 w-3" aria-hidden="true" />
            {contact.email}
          </span>
        )}
        {contact.telegram_username && (
          <span className="inline-flex items-center gap-1 text-primary font-mono">
            @{contact.telegram_username.replace(/^@/, '')}
          </span>
        )}
      </div>
      {contact.invited_at && (
        <span className="text-xs text-muted-foreground mt-0.5">
          {t('counterparties.detail.invited')}: {formatDistanceToNow(new Date(contact.invited_at), { addSuffix: true, locale: dateLocale })}
        </span>
      )}
    </div>
  );
}

export function CounterpartiesPage() {
  const { t } = useTranslation();
  const { data: contacts, isLoading, isError, refetch } = useContacts();
  const dateLocale = activeDateFnsLocale();
  const listParams = useListParams([] as const, { urlKey: 'counterparties', defaultOrdering: 'name' });
  const [selected, setSelected] = useState<ClientRow | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const canManageDeals = useHasCompanyPermission('deal.manage');
  const inviteMut = useInviteContact();
  const [invitingId, setInvitingId] = useState<number | null>(null);

  const handleInvite = async (contact: Contact) => {
    setInvitingId(contact.id);
    try {
      const res = await inviteMut.mutateAsync({ contactId: contact.id });
      if (res.email_sent) {
        toast.success(t('counterparties.invite.successEmail', { email: contact.email }), {
          action: res.invite_url || res.telegram_url ? {
            label: t('counterparties.invite.copyLink'),
            onClick: () => {
              void navigator.clipboard.writeText(res.telegram_url || res.invite_url);
              toast.info(t('counterparties.invite.linkCopied'));
            },
          } : undefined,
        });
      } else {
        toast.success(t('counterparties.invite.successLink'), {
          action: {
            label: t('counterparties.invite.copyLink'),
            onClick: () => {
              void navigator.clipboard.writeText(res.telegram_url || res.invite_url);
              toast.info(t('counterparties.invite.linkCopied'));
            },
          },
        });
      }
    } catch (err) {
      toast.error(translateApiError(err));
    } finally {
      setInvitingId(null);
    }
  };

  const rows = useMemo(() => groupContactsByCompany(contacts ?? []), [contacts]);

  const columns: ResponsiveColumn<ClientRow>[] = [
    {
      id: 'counterparty', sortKey: 'name', header: t('counterparties.table.counterparty'), mobileTitle: true,
      cell: (row) => (
        <span className="inline-flex items-center gap-2 font-medium">
          {row.name}
          {!row.isRegistered && <Badge variant="outline">{t('counterparties.offline')}</Badge>}
        </span>
      ),
    },
    {
      id: 'contact', header: t('counterparties.table.contact'),
      cell: (row) => (row.primary ? <ContactLine contact={row.primary} /> : <span className="text-muted-foreground">—</span>),
    },
    {
      id: 'contacts', sortKey: 'contacts', header: t('counterparties.table.contacts'), className: 'text-right',
      cell: (row) => <span className="tabular-nums">{row.contacts.length}</span>,
    },
    {
      id: 'created', sortKey: 'created', header: t('counterparties.table.added'),
      cell: (row) => (
        <span className="text-xs text-muted-foreground">
          {formatDistanceToNow(new Date(row.createdAt), { addSuffix: true, locale: dateLocale })}
        </span>
      ),
    },
  ];

  return (
    <PageShell
      title={t('counterparties.title.clients')}
      description={t('counterparties.description.clients')}
      icon={<Users className="h-5 w-5" />}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('counterparties.searchPlaceholder')}
        newLabel={t('counterparties.newClient')}
        onNew={() => setCreateOpen(true)}
      />
      <CreateOfflineClientDialog open={createOpen} onOpenChange={setCreateOpen} />

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(rows, listParams, {
              searchFields: (row) => [
                row.name,
                ...row.contacts.flatMap((contact) => [contact.name, contact.phone, contact.email]),
              ],
              sortAccessors: {
                name: (row) => row.name.toLocaleLowerCase(),
                contacts: (row) => row.contacts.length,
                created: (row) => row.createdAt,
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) {
              return (
                <EmptyState
                  icon={<Users className="h-5 w-5" />}
                  message={t('counterparties.emptyState')}
                  hint={t('counterparties.emptyStateHintClients')}
                  action={{ label: t('counterparties.newClient'), onClick: () => setCreateOpen(true) }}
                />
              );
            }
            return (
              <>
                <ResponsiveDataTable
                  columns={columns}
                  rows={pageItems}
                  getRowId={(row) => row.id}
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
              <SheetTitle>{selected.name}</SheetTitle>
              <SheetDescription className="flex flex-wrap items-center gap-2">
                <Badge variant={selected.isRegistered ? 'secondary' : 'outline'}>
                  {selected.isRegistered ? t('counterparties.registered') : t('counterparties.offline')}
                </Badge>
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 p-4">
              <div className="space-y-3">
                <p className="text-sm font-medium">{t('counterparties.detail.contacts')}</p>
                <ul className="space-y-3">
                  {selected.contacts.map((contact) => (
                    <li key={contact.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-lg border bg-card/50">
                      <ContactLine contact={contact} />
                      <div className="flex items-center gap-2 self-end sm:self-center shrink-0">
                        {contact.is_primary && <Badge variant="secondary">{t('counterparties.detail.primary')}</Badge>}
                        {canManageDeals && (
                          <Button
                            size="sm"
                            variant={contact.invited_at ? 'outline' : 'default'}
                            onClick={() => handleInvite(contact)}
                            disabled={invitingId === contact.id}
                            className="gap-1.5 text-xs h-8"
                          >
                            {invitingId === contact.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                            ) : (
                              <Send className="h-3.5 w-3.5" aria-hidden="true" />
                            )}
                            {contact.invited_at ? t('counterparties.detail.reinvite') : t('counterparties.detail.invite')}
                          </Button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
              <CompanyTimeline companyId={selected.id} />
            </div>
          </SheetContent>
        </Sheet>
      )}
    </PageShell>
  );
}

export default CounterpartiesPage;
