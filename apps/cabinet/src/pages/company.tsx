import { useEffect, useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Building2, CheckCircle2, FileText, Handshake, Pencil, Shield, UserMinus, UserPlus, Users, X } from 'lucide-react';
import { toast } from '@/lib/toast';

import { apiErrorKey } from '@/api/errors';
import type { Company, PartnerKind, Schemas, TeamInvite, TeamMember } from '@/api/portal';
import { getPartnerContractPdfUrl } from '@/api/portal';
import {
  useAgreeCompanyPartnerContract,
  useCompany,
  useCompanyPartnerApplication,
  useCompanySecurityLog,
  useDeactivateTeamMember,
  useInviteTeamMember,
  useSubmitCompanyPartnerApplication,
  useTeam,
  useUpdateCompany,
  useUpdateTeamMember,
} from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
import { DetailList } from '@/components/Details';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { UnsavedChangesBar } from '@/components/UnsavedChangesBar';
import { DetailSkeleton, ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ToneBadge } from '@/components/StatusBadge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { findCountry } from '@/lib/countries';
import { LOCALES } from '@/i18n/locales';
import { companyChanges, validateInvite, type CompanyFormDraft, type InviteDraft, type InviteProblem } from '@/lib/company';
import { formatDateTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { CanAct } from '@/session/CanAct';
import { useMe } from '@/session/useMe';

/**
 * Компания и команда клиента (B2B `SettingsPage`: разделы «профиль» и «команда»). Правка реквизитов и
 * приглашение коллеги — только контакту с правом действовать; права коллег и основной контакт меняет
 * менеджер в ERP (в контракте нет такого действия). 2FA, нумерация, шаблоны B2B — не сюда (CONVENTIONS.md §4).
 */
export function CompanyPage() {
  const { t } = useTranslation();
  const company = useCompany();
  const me = useMe().data;
  const isAdmin = me?.contact?.is_admin === true;
  const [editing, setEditing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const stopEditing = () => {
    setConfirmClose(false);
    setDirty(false);
    setEditing(false);
  };

  return (
    <>
      <PageHeader
        title={t('pages.company.title')}
        icon={Building2}
        actions={
          !company.data ? null : editing ? (
            <Button variant="outline" onClick={() => (dirty ? setConfirmClose(true) : stopEditing())}>
              <X aria-hidden="true" />
              {t('pages.company.closeEdit')}
            </Button>
          ) : (
            <CanAct>
              <Button variant="outline" onClick={() => setEditing(true)}>
                <Pencil aria-hidden="true" />
                {t('pages.company.edit')}
              </Button>
            </CanAct>
          )
        }
      />
      {company.isPending ? (
        <DetailSkeleton />
      ) : company.isError ? (
        <ErrorState error={company.error} onRetry={() => void company.refetch()} />
      ) : editing ? (
        <CompanyForm company={company.data} onDone={stopEditing} onDirtyChange={setDirty} />
      ) : (
        <div className="flex flex-col gap-4">
          {company.data.relationship_status === 'suspended' && (
            <Alert variant="destructive" className="border-warning/50 bg-warning/10 text-warning-foreground">
              <AlertTriangle className="size-4 text-warning" aria-hidden="true" />
              <AlertDescription>
                {t(
                  'pages.company.relationship.suspendedAlert',
                  'Отношения временно приостановлены. Доступ открыт в режиме чтения архива.',
                )}
              </AlertDescription>
            </Alert>
          )}
          {company.data.relationship_status === 'terminated' && (
            <Alert variant="destructive" className="border-destructive/50 bg-destructive/10">
              <AlertTriangle className="size-4 text-destructive" aria-hidden="true" />
              <AlertDescription>
                {t(
                  'pages.company.relationship.terminatedAlert',
                  'Отношения завершены. Архив документов доступен для просмотра и выгрузки.',
                )}
              </AlertDescription>
            </Alert>
          )}
          <Card>
            <CardContent>
              <DetailList
                className="sm:grid-cols-1"
                items={[
                  { label: t('pages.company.fields.name'), value: company.data.name },
                  {
                    label: t('pages.company.fields.relationshipStatus', 'Статус отношений'),
                    value: (
                      <div className="flex flex-wrap items-center gap-2">
                        <ToneBadge
                          tone={
                            company.data.relationship_status === 'active'
                              ? 'success'
                              : company.data.relationship_status === 'suspended'
                              ? 'warning'
                              : company.data.relationship_status === 'terminated'
                              ? 'neutral'
                              : 'info'
                          }
                        >
                          {t(`pages.company.relationship.${company.data.relationship_status || 'active'}`)}
                        </ToneBadge>
                        {company.data.relationships?.map((rel, idx) => (
                          <span key={idx} className="text-xs text-muted-foreground">
                            ({t(`roles.${rel.role}`)}{rel.contract_number ? ` · № ${rel.contract_number}` : ''})
                          </span>
                        ))}
                      </div>
                    ),
                  },
                  ...(company.data.country
                    ? [{ label: t('pages.company.fields.country'), value: company.data.country.name }]
                    : []),
                  {
                    label:
                      company.data.country && company.data.country.code !== 'UZ'
                        ? t('pages.company.fields.registrationNumber')
                        : t('pages.company.fields.inn'),
                    value:
                      (company.data.country && company.data.country.code !== 'UZ'
                        ? company.data.registration_number
                        : company.data.inn) || t('pages.company.notSet'),
                  },
                  { label: t('pages.company.fields.legalAddress'), value: company.data.legal_address || t('pages.company.notSet') },
                  {
                    label: t('pages.company.fields.bankDetails'),
                    value: (
                      <div className="flex flex-col gap-1">
                        <span className="whitespace-pre-line">{company.data.bank_details || t('pages.company.notSet')}</span>
                        {!isAdmin && (
                          <span className="text-xs text-muted-foreground flex items-center gap-1">
                            <Shield className="size-3 text-muted-foreground" aria-hidden="true" />
                            {t('pages.company.fields.bankAdminOnlyBadge', 'Редактировать может только администратор')}
                          </span>
                        )}
                      </div>
                    ),
                  },
                  { label: t('pages.company.fields.language'), value: t(`languages.${company.data.language}`) },
                ]}
              />
            </CardContent>
          </Card>
          <PartnerApplicationCard />
          <Button asChild variant="outline" className="self-start">
            <Link to="/team">
              <Users aria-hidden="true" />
              {t('pages.company.toTeam')}
            </Link>
          </Button>
          {isAdmin && <SecurityLogCard />}
        </div>
      )}
      <ActionDialog
        open={confirmClose}
        onOpenChange={setConfirmClose}
        title={t('unsavedGuard.title')}
        description={t('unsavedGuard.text')}
        confirmLabel={t('unsavedGuard.leave')}
        confirmVariant="destructive"
        cancelLabel={t('unsavedGuard.stay')}
        pending={false}
        onSubmit={stopEditing}
      />
    </>
  );
}

/**
 * Правка реквизитов: кнопка сохранения одна — в баре несохранённых изменений (`UnsavedChangesBar`, K9), бар — последний
 * элемент формы, место под него зарезервировано. Enter в поле тоже сохраняет (обратимо: реквизиты можно поправить снова).
 */
function CompanyForm({
  company,
  onDone,
  onDirtyChange,
}: {
  company: Company;
  onDone: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const update = useUpdateCompany();
  const me = useMe().data;
  const isAdmin = me?.contact?.is_admin === true;
  const isUzbekistan = !company.country || company.country.code === 'UZ';
  const [draft, setDraft] = useState<CompanyFormDraft>({
    name: company.name,
    inn: company.inn ?? '',
    registration_number: company.registration_number ?? '',
    country_code: company.country?.code ?? 'UZ',
    legal_address: company.legal_address ?? '',
    bank_details: company.bank_details ?? '',
    language: company.language,
  });
  const [nameMissing, setNameMissing] = useState(false);

  const set = <K extends keyof CompanyFormDraft>(key: K, value: CompanyFormDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.name.trim()) {
      setNameMissing(true);
      return;
    }
    const changes = companyChanges(company, draft);
    if (Object.keys(changes).length === 0) {
      onDone();
      return;
    }
    update.mutate(changes, {
      onSuccess: () => {
        toast.success(t('pages.company.saved'));
        onDone();
      },
    });
  };

  const isDirty = Boolean(Object.keys(companyChanges(company, draft)).length);
  useEffect(() => onDirtyChange(isDirty), [isDirty, onDirtyChange]);

  const reset = () => {
    setDraft({
      name: company.name,
      inn: company.inn ?? '',
      registration_number: company.registration_number ?? '',
      country_code: company.country?.code ?? 'UZ',
      legal_address: company.legal_address ?? '',
      bank_details: company.bank_details ?? '',
      language: company.language,
    });
    setNameMissing(false);
  };

  return (
    <Card>
      <CardContent>
        <form onSubmit={submit} noValidate className="flex flex-col gap-4 [&_:is(input,textarea,button)]:scroll-mb-40">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-name`}>{t('pages.company.fields.name')}</Label>
            <Input
              id={`${id}-name`}
              value={draft.name}
              maxLength={300}
              required
              aria-invalid={nameMissing || undefined}
              aria-describedby={nameMissing ? `${id}-name-error` : undefined}
              onChange={(event) => {
                set('name', event.target.value);
                setNameMissing(false);
              }}
            />
            {nameMissing ? (
              <p id={`${id}-name-error`} className="text-sm text-destructive">
                {t('pages.company.nameRequired')}
              </p>
            ) : null}
          </div>
          {isUzbekistan ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-inn`}>{t('pages.company.fields.inn')}</Label>
              <Input
                id={`${id}-inn`}
                inputMode="numeric"
                value={draft.inn}
                maxLength={20}
                onChange={(event) => set('inn', event.target.value)}
              />
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-reg`}>{t('pages.company.fields.registrationNumber')}</Label>
              <Input
                id={`${id}-reg`}
                value={draft.registration_number}
                maxLength={50}
                onChange={(event) => set('registration_number', event.target.value)}
              />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-address`}>{t('pages.company.fields.legalAddress')}</Label>
            <Textarea
              id={`${id}-address`}
              rows={2}
              value={draft.legal_address}
              maxLength={500}
              onChange={(event) => set('legal_address', event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor={`${id}-bank`}>{t('pages.company.fields.bankDetails')}</Label>
              {!isAdmin && (
                <ToneBadge tone="warning" className="text-xs py-0 px-1.5">
                  <Shield className="size-3 mr-1 inline" aria-hidden="true" />
                  {t('pages.company.fields.bankAdminOnlyBadge', 'Только администратор')}
                </ToneBadge>
              )}
            </div>
            <Textarea
              id={`${id}-bank`}
              rows={3}
              value={draft.bank_details}
              maxLength={1000}
              disabled={!isAdmin}
              onChange={(event) => set('bank_details', event.target.value)}
              className={!isAdmin ? 'bg-muted/50 cursor-not-allowed opacity-80' : undefined}
            />
            {!isAdmin ? (
              <p className="text-xs text-muted-foreground">
                {t(
                  'pages.company.fields.bankDetailsAdminOnly',
                  'Изменение банковских реквизитов доступно только администратору компании.',
                )}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                <Shield className="size-3 text-primary shrink-0" aria-hidden="true" />
                <span>
                  {t(
                    'pages.company.fields.bankDetailsAdminNotice',
                    'При изменении реквизитов все администраторы компании получат уведомление безопасности.',
                  )}
                </span>
              </p>
            )}
          </div>
          <LanguageChoice
            label={t('pages.company.fields.language')}
            value={draft.language}
            onChange={(language) => set('language', language)}
          />
          {update.isError ? (
            <Alert variant="destructive">
              <AlertDescription>{t(apiErrorKey(update.error))}</AlertDescription>
            </Alert>
          ) : null}
          <UnsavedChangesBar
            dirty={isDirty}
            onSave={() => submit({ preventDefault: () => {} } as FormEvent)}
            onReset={reset}
            pending={update.isPending}
          />
        </form>
      </CardContent>
    </Card>
  );
}

/** Выбор языка из реестра локалей — кнопки-переключатели (на телефоне удобнее выпадающего списка). */
function LanguageChoice({
  label,
  value,
  onChange,
}: {
  label: string;
  value: Schemas['Language'];
  onChange: (value: Schemas['Language']) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex flex-wrap gap-2">
        {LOCALES.map((locale) => (
          <Button
            key={locale.code}
            type="button"
            size="sm"
            variant={value === locale.code ? 'default' : 'outline'}
            aria-pressed={value === locale.code}
            className="rounded-full"
            onClick={() => onChange(locale.code)}
          >
            {locale.nativeName}
          </Button>
        ))}
      </div>
    </div>
  );
}

function SecurityLogCard() {
  const { t } = useTranslation();
  const securityLog = useCompanySecurityLog();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Shield className="size-4 text-primary" aria-hidden="true" />
          {t('pages.company.securityLog.title', 'Журнал безопасности компании')}
        </CardTitle>
        <CardDescription>
          {t(
            'pages.company.securityLog.description',
            'История входов, изменений прав сотрудников и настроек безопасности',
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {securityLog.isPending ? (
          <ListSkeleton />
        ) : securityLog.isError ? (
          <p className="text-sm text-destructive">
            {t('pages.company.securityLog.error', 'Не удалось загрузить журнал безопасности')}
          </p>
        ) : !securityLog.data?.items?.length ? (
          <p className="text-sm text-muted-foreground">
            {t('pages.company.securityLog.empty', 'Событий безопасности пока не зафиксировано')}
          </p>
        ) : (
          <ul
            className="flex flex-col divide-y divide-border text-sm"
            aria-label={t('pages.company.securityLog.title', 'Журнал безопасности компании')}
          >
            {securityLog.data.items.map((event) => (
              <li key={event.id} className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <ToneBadge
                      tone={
                        event.event_type === 'login'
                          ? 'info'
                          : event.event_type === 'bank_details_changed' || event.event_type === 'member_deactivated'
                          ? 'warning'
                          : 'neutral'
                      }
                      className="text-xs"
                    >
                      {t(`pages.company.securityLog.events.${event.event_type}`)}
                    </ToneBadge>
                    <span className="font-medium text-foreground">{event.actor_name}</span>
                    {event.target_name && (
                      <span className="text-xs text-muted-foreground">→ {event.target_name}</span>
                    )}
                  </div>
                  <time className="text-xs text-muted-foreground" dateTime={event.created_at}>
                    {formatDateTime(event.created_at)}
                  </time>
                </div>
                {event.details && <p className="text-xs text-muted-foreground">{event.details}</p>}
                {(event.ip_address || event.user_agent) && (
                  <p className="text-xs text-muted-foreground/80">
                    {[event.ip_address, event.user_agent].filter(Boolean).join(' · ')}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

// --- команда ----------------------------------------------------------------------------------

export function TeamPage() {
  const { t } = useTranslation();
  const me = useMe();
  const meId = me.data?.contact.id;
  const isMeAdmin = Boolean(me.data?.contact.is_admin);
  const team = useTeam();
  const [inviting, setInviting] = useState(false);
  const [memberToDeactivate, setMemberToDeactivate] = useState<TeamMember | null>(null);

  const updateMember = useUpdateTeamMember();
  const deactivateMember = useDeactivateTeamMember();

  const handleToggleCanAct = (member: TeamMember) => {
    updateMember.mutate(
      { id: member.id, body: { can_act: !member.can_act } },
      {
        onSuccess: (updated) => {
          toast.success(t('pages.team.updated', { name: updated.name }));
        },
        onError: (err) => {
          toast.error(t(apiErrorKey(err)));
        },
      },
    );
  };

  const handleToggleAdmin = (member: TeamMember) => {
    updateMember.mutate(
      { id: member.id, body: { is_admin: !member.is_admin } },
      {
        onSuccess: (updated) => {
          toast.success(t('pages.team.updated', { name: updated.name }));
        },
        onError: (err) => {
          toast.error(t(apiErrorKey(err)));
        },
      },
    );
  };

  const handleDeactivate = () => {
    if (!memberToDeactivate) return;
    deactivateMember.mutate(memberToDeactivate.id, {
      onSuccess: () => {
        toast.success(t('pages.team.deactivated', { name: memberToDeactivate.name }));
        setMemberToDeactivate(null);
      },
      onError: (err) => {
        toast.error(t(apiErrorKey(err)));
      },
    });
  };

  const isPending = updateMember.isPending || deactivateMember.isPending;

  return (
    <>
      <PageHeader
        title={t('pages.team.title')}
        icon={Users}
        actions={
          <CanAct>
            <Button onClick={() => setInviting(true)}>
              <UserPlus aria-hidden="true" />
              {t('pages.team.invite')}
            </Button>
          </CanAct>
        }
      />
      {team.isPending ? (
        <ListSkeleton />
      ) : team.isError ? (
        <ErrorState error={team.error} onRetry={() => void team.refetch()} />
      ) : team.data.length === 0 ? (
        <EmptyState icon={Users} title={t('pages.team.emptyTitle')} text={t('pages.team.emptyText')} />
      ) : (
        <ul className="grid gap-3 lg:grid-cols-2" aria-label={t('pages.team.title')}>
          {team.data.map((member) => (
            <li key={member.id}>
              <MemberCard
                member={member}
                isMe={member.id === meId}
                isMeAdmin={isMeAdmin}
                onToggleCanAct={handleToggleCanAct}
                onToggleAdmin={handleToggleAdmin}
                onDeactivate={(m) => setMemberToDeactivate(m)}
                isPending={isPending}
              />
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-xs text-muted-foreground">{t('pages.team.rightsHint')}</p>
      <InviteDialog open={inviting} onOpenChange={setInviting} isMeAdmin={isMeAdmin} />

      <ActionDialog
        open={Boolean(memberToDeactivate)}
        onOpenChange={(open) => !open && setMemberToDeactivate(null)}
        title={t('pages.team.deactivateTitle')}
        description={t('pages.team.deactivateDesc', { name: memberToDeactivate?.name })}
        confirmLabel={t('pages.team.deactivateConfirm')}
        pending={deactivateMember.isPending}
        error={deactivateMember.error}
        onSubmit={handleDeactivate}
      />
    </>
  );
}

function MemberCard({
  member,
  isMe,
  isMeAdmin,
  onToggleCanAct,
  onToggleAdmin,
  onDeactivate,
  isPending,
}: {
  member: TeamMember;
  isMe: boolean;
  isMeAdmin: boolean;
  onToggleCanAct: (member: TeamMember) => void;
  onToggleAdmin: (member: TeamMember) => void;
  onDeactivate: (member: TeamMember) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  return (
    <article className="portal-card flex h-full min-w-0 flex-col gap-3 rounded-2xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold break-words">{member.name}</h2>
        {isMe ? <ToneBadge tone="info">{t('pages.team.you')}</ToneBadge> : null}
        {member.is_primary ? <ToneBadge tone="neutral">{t('pages.team.primary')}</ToneBadge> : null}
        {member.is_admin ? <ToneBadge tone="warning">{t('pages.team.admin')}</ToneBadge> : null}
      </div>
      <DetailList
        items={[
          member.email ? { label: t('pages.team.email'), value: <span className="break-all">{member.email}</span> } : null,
          member.phone ? { label: t('pages.team.phone'), value: member.phone } : null,
          { label: t('pages.team.telegram'), value: member.has_telegram ? t('pages.team.telegramLinked') : t('pages.team.telegramNotLinked') },
          { label: t('pages.team.rights'), value: member.can_act ? t('pages.team.canAct') : t('pages.team.viewOnly') },
          {
            label: t('pages.team.lastLogin'),
            value: member.last_login_at
              ? formatDateTime(member.last_login_at)
              : member.invited_at
                ? t('pages.team.invitedAt', { date: formatDateTime(member.invited_at) })
                : t('pages.team.neverLoggedIn'),
          },
        ]}
      />
      {isMeAdmin && !isMe && !member.is_primary ? (
        <div className="mt-auto flex flex-wrap gap-2 border-t border-border pt-3">
          <Button
            size="sm"
            variant="outline"
            disabled={isPending}
            onClick={() => onToggleCanAct(member)}
          >
            {member.can_act ? t('pages.team.revokeCanAct') : t('pages.team.grantCanAct')}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={isPending}
            onClick={() => onToggleAdmin(member)}
          >
            {member.is_admin ? t('pages.team.revokeAdmin') : t('pages.team.grantAdmin')}
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={isPending}
            onClick={() => onDeactivate(member)}
          >
            <UserMinus className="size-4 mr-1" aria-hidden="true" />
            {t('pages.team.deactivate')}
          </Button>
        </div>
      ) : null}
    </article>
  );
}

const emptyInvite = (language: Schemas['Language']): InviteDraft => ({
  name: '',
  email: '',
  phone: '',
  language,
  can_act: false,
  channels: { email: true, telegram: false },
});

function InviteDialog({
  open,
  onOpenChange,
  isMeAdmin,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isMeAdmin: boolean;
}) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const invite = useInviteTeamMember();
  const company = useCompany();
  const countryCode = company.data?.country?.code ?? 'UZ';
  const countryMeta = findCountry(countryCode);
  const phonePlaceholder = countryMeta.phonePlaceholder;

  const defaultLanguage = (LOCALES.find((locale) => locale.code === i18n.language)?.code ?? 'ru') as Schemas['Language'];
  const [draft, setDraft] = useState<InviteDraft>(() => emptyInvite(defaultLanguage));
  const [problems, setProblems] = useState<InviteProblem[]>([]);

  const close = (next: boolean) => {
    if (!next) {
      setDraft(emptyInvite(defaultLanguage));
      setProblems([]);
      invite.reset();
    }
    onOpenChange(next);
  };
  const set = (patch: Partial<InviteDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setProblems([]);
  };

  const submit = () => {
    const result = validateInvite(draft);
    if (!result.ok) {
      setProblems(result.problems);
      return;
    }
    invite.mutate(result.body satisfies TeamInvite, {
      onSuccess: (member) => {
        toast.success(t('pages.team.invited', { name: member.name }));
        close(false);
      },
    });
  };

  const has = (problem: InviteProblem) => problems.includes(problem);

  return (
    <ActionDialog
      open={open}
      onOpenChange={close}
      title={t('pages.team.inviteTitle')}
      description={t('pages.team.inviteText')}
      confirmLabel={t('pages.team.inviteConfirm')}
      pending={invite.isPending}
      error={invite.error}
      message={problems.length ? problems.map((problem) => t(`pages.team.problems.${problem}`)).join(' ') : null}
      onSubmit={submit}
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-name`}>{t('pages.team.fields.name')}</Label>
          <Input
            id={`${id}-name`}
            value={draft.name}
            maxLength={200}
            autoComplete="off"
            aria-invalid={has('name') || undefined}
            onChange={(event) => set({ name: event.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-email`}>{t('pages.team.fields.email')}</Label>
          <Input
            id={`${id}-email`}
            type="email"
            value={draft.email}
            autoComplete="off"
            aria-invalid={has('email') || undefined}
            onChange={(event) => set({ email: event.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-phone`}>{t('pages.team.fields.phone')}</Label>
          <Input
            id={`${id}-phone`}
            type="tel"
            value={draft.phone}
            maxLength={32}
            autoComplete="off"
            placeholder={phonePlaceholder}
            aria-invalid={has('phone') || undefined}
            onChange={(event) => set({ phone: event.target.value })}
          />
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm font-medium">{t('pages.team.fields.channels')}</legend>
          {(['email', 'telegram'] as const).map((channel) => (
            <div key={channel} className="flex items-center gap-2">
              <Checkbox
                id={`${id}-channel-${channel}`}
                checked={draft.channels[channel]}
                aria-invalid={has('channels') || undefined}
                onCheckedChange={(checked) => set({ channels: { ...draft.channels, [channel]: checked === true } })}
              />
              <Label htmlFor={`${id}-channel-${channel}`} className="font-normal">
                {t(`pages.team.channels.${channel}`)}
              </Label>
            </div>
          ))}
        </fieldset>
        <LanguageChoice label={t('pages.team.fields.language')} value={draft.language} onChange={(language) => set({ language })} />
        <div className={cn('flex items-start gap-2 rounded-md border p-3')}>
          <Checkbox
            id={`${id}-can-act`}
            checked={draft.can_act}
            onCheckedChange={(checked) => set({ can_act: checked === true })}
            aria-describedby={`${id}-can-act-hint`}
          />
          <div className="flex flex-col gap-1">
            <Label htmlFor={`${id}-can-act`}>{t('pages.team.fields.canAct')}</Label>
            <p id={`${id}-can-act-hint`} className="text-xs text-muted-foreground">
              {t('pages.team.fields.canActHint')}
            </p>
          </div>
        </div>
        {isMeAdmin ? (
          <div className={cn('flex items-start gap-2 rounded-md border p-3')}>
            <Checkbox
              id={`${id}-is-admin`}
              checked={draft.is_admin ?? false}
              onCheckedChange={(checked) => set({ is_admin: checked === true })}
              aria-describedby={`${id}-is-admin-hint`}
            />
            <div className="flex flex-col gap-1">
              <Label htmlFor={`${id}-is-admin`}>{t('pages.team.fields.roleAdmin')}</Label>
              <p id={`${id}-is-admin-hint`} className="text-xs text-muted-foreground">
                {t('pages.team.fields.roleAdminHint')}
              </p>
            </div>
          </div>
        ) : null}
      </div>
    </ActionDialog>
  );
}

const PARTNER_KINDS: PartnerKind[] = ['supplier', 'manufacturer', 'principal', 'other'];

function PartnerStepper({ status }: { status: string }) {
  const { t } = useTranslation();
  const steps = [
    { key: 'application', label: t('pages.company.partner.steps.application') },
    { key: 'draft', label: t('pages.company.partner.steps.draft') },
    { key: 'director', label: t('pages.company.partner.steps.director') },
    { key: 'active', label: t('pages.company.partner.steps.active') },
  ];

  const getStepState = (index: number): 'completed' | 'current' | 'pending' => {
    if (status === 'rejected') return index === 0 ? 'completed' : 'pending';
    if (status === 'approved') return 'completed';
    if (status === 'candidate_agreed') {
      if (index < 2) return 'completed';
      if (index === 2) return 'current';
      return 'pending';
    }
    if (status === 'contract_sent') {
      if (index < 1) return 'completed';
      if (index === 1) return 'current';
      return 'pending';
    }
    if (index === 0) return 'current';
    return 'pending';
  };

  return (
    <div className="py-2 mb-4" aria-label="Прогресс партнёрства">
      <div className="flex items-center justify-between gap-1">
        {steps.map((step, idx) => {
          const state = getStepState(idx);
          return (
            <div key={step.key} className="flex-1 flex flex-col items-center text-center">
              <div className="flex items-center w-full">
                {idx > 0 && (
                  <div
                    className={cn(
                      'flex-1 h-0.5 transition-colors',
                      state === 'completed' || (state === 'current' && idx > 0)
                        ? 'bg-primary'
                        : 'bg-muted',
                    )}
                  />
                )}
                <div
                  className={cn(
                    'size-6 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 transition-colors',
                    state === 'completed' && 'bg-primary text-primary-foreground',
                    state === 'current' && 'border-2 border-primary bg-background text-primary',
                    state === 'pending' && 'border-2 border-muted bg-background text-muted-foreground',
                  )}
                >
                  {state === 'completed' ? <CheckCircle2 className="size-3.5" /> : idx + 1}
                </div>
                {idx < steps.length - 1 && (
                  <div
                    className={cn(
                      'flex-1 h-0.5 transition-colors',
                      state === 'completed' ? 'bg-primary' : 'bg-muted',
                    )}
                  />
                )}
              </div>
              <span
                className={cn(
                  'text-xs mt-1 font-medium leading-tight',
                  state === 'current' ? 'text-foreground' : 'text-muted-foreground',
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function PartnerApplicationCard() {
  const { t } = useTranslation();
  const partnerQuery = useCompanyPartnerApplication();
  const submitMutation = useSubmitCompanyPartnerApplication();
  const agreeMutation = useAgreeCompanyPartnerContract();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [agreeDialogOpen, setAgreeDialogOpen] = useState(false);
  const [agreeNotes, setAgreeNotes] = useState('');
  const [kind, setKind] = useState<PartnerKind>('supplier');
  const [categories, setCategories] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);

  if (partnerQuery.isPending) {
    return <DetailSkeleton />;
  }

  const data = partnerQuery.data;
  const isPartner = Boolean(data?.already_partner);
  const hasApp = Boolean(data?.has_application);
  const app = data?.application;

  if (isPartner && !hasApp) {
    return (
      <Card className="border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Handshake className="size-5 text-primary" aria-hidden="true" />
            <CardTitle>
              <h2 className="text-base">{t('pages.company.partner.alreadyPartnerTitle')}</h2>
            </CardTitle>
          </div>
          <CardDescription>{t('pages.company.partner.alreadyPartnerDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild variant="outline">
            <Link to="/my-products">{t('pages.company.partner.toMyProducts')}</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (hasApp && app) {
    const toneByStatus: Record<string, 'neutral' | 'info' | 'success' | 'warning'> = {
      submitted: 'info',
      contract_sent: 'warning',
      candidate_agreed: 'info',
      approved: 'success',
      rejected: 'neutral',
    };

    const handleAgree = () => {
      agreeMutation.mutate(
        { notes: agreeNotes.trim() || undefined },
        {
          onSuccess: () => {
            setAgreeDialogOpen(false);
            setAgreeNotes('');
            toast.success(t('pages.company.partner.agreeSuccess'));
          },
        },
      );
    };

    return (
      <>
        <Card className="border-border">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Handshake className="size-5 text-primary" aria-hidden="true" />
                <CardTitle>
                  <h2 className="text-base">{t('pages.company.partner.cardTitle')}</h2>
                </CardTitle>
              </div>
              <ToneBadge tone={toneByStatus[app.status] ?? 'neutral'}>
                {t(`pages.company.partner.status.${app.status}`)}
              </ToneBadge>
            </div>
            <CardDescription>
              {app.status === 'contract_sent'
                ? t('pages.company.partner.contractSentDesc')
                : app.status === 'candidate_agreed'
                ? t('pages.company.partner.contractAgreedDesc')
                : t('pages.company.partner.applicationPendingDesc')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <PartnerStepper status={app.status} />

            <DetailList
              className="sm:grid-cols-1"
              items={[
                { label: t('pages.becomePartner.fields.kind'), value: t(`pages.becomePartner.fields.kinds.${app.kind}`) },
                { label: t('pages.becomePartner.fields.categoriesDescription'), value: app.categories_description },
                { label: t('pages.company.partner.appliedAt'), value: formatDateTime(app.created_at) },
                ...(app.contract_number
                  ? [
                      {
                        label: t('pages.company.partner.contractNumber'),
                        value: `${app.contract_number}${app.contract_date ? ` от ${app.contract_date}` : ''}`,
                      },
                    ]
                  : []),
              ]}
            />

            {(app.status === 'contract_sent' || app.status === 'candidate_agreed' || app.status === 'approved') && (
              <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-border">
                <Button asChild variant="outline">
                  <a href={getPartnerContractPdfUrl()} target="_blank" rel="noopener noreferrer">
                    <FileText className="size-4 mr-2" aria-hidden="true" />
                    {t('pages.company.partner.downloadDraftPdf')}
                  </a>
                </Button>

                {app.status === 'contract_sent' && (
                  <CanAct
                    fallback={
                      <p className="text-xs text-muted-foreground">{t('pages.company.partner.onlyCanAct')}</p>
                    }
                  >
                    <Button onClick={() => setAgreeDialogOpen(true)}>
                      <CheckCircle2 className="size-4 mr-2" aria-hidden="true" />
                      {t('pages.company.partner.agreeContractBtn')}
                    </Button>
                  </CanAct>
                )}

                {app.status === 'approved' && (
                  <Button asChild>
                    <Link to="/my-products">{t('pages.company.partner.toMyProducts')}</Link>
                  </Button>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <ActionDialog
          open={agreeDialogOpen}
          onOpenChange={setAgreeDialogOpen}
          title={t('pages.company.partner.agreeDialogTitle')}
          description={t('pages.company.partner.agreeDialogDesc')}
          confirmLabel={t('pages.company.partner.agreeSubmit')}
          pending={agreeMutation.isPending}
          error={agreeMutation.error}
          onSubmit={handleAgree}
        >
          <div className="flex flex-col gap-2 pt-2">
            <Label htmlFor="agree-notes">{t('pages.company.partner.agreeNotesLabel')}</Label>
            <Textarea
              id="agree-notes"
              value={agreeNotes}
              onChange={(e) => setAgreeNotes(e.target.value)}
              placeholder="..."
              maxLength={1000}
            />
          </div>
        </ActionDialog>
      </>
    );
  }

  const handleOpen = () => {
    setKind('supplier');
    setCategories('');
    setValidationError(null);
    setDialogOpen(true);
  };

  const handleSubmit = () => {
    setValidationError(null);
    if (!categories.trim() || categories.trim().length < 5) {
      setValidationError(t('pages.becomePartner.errors.categoriesDescriptionTooShort'));
      return;
    }
    submitMutation.mutate(
      { kind, categories_description: categories.trim() },
      {
        onSuccess: () => {
          setDialogOpen(false);
          toast.success(t('pages.company.partner.dialogSuccess'));
        },
      },
    );
  };

  return (
    <>
      <Card className="border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Handshake className="size-5 text-primary" aria-hidden="true" />
            <CardTitle>
              <h2 className="text-base">{t('pages.company.partner.cardTitle')}</h2>
            </CardTitle>
          </div>
          <CardDescription>{t('pages.company.partner.notPartnerDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <CanAct
            fallback={<p className="text-xs text-muted-foreground">{t('pages.company.partner.onlyCanAct')}</p>}
          >
            <Button variant="outline" onClick={handleOpen}>
              <Handshake aria-hidden="true" />
              {t('pages.company.partner.applyBtn')}
            </Button>
          </CanAct>
        </CardContent>
      </Card>

      <ActionDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title={t('pages.company.partner.dialogTitle')}
        description={t('pages.company.partner.dialogDesc')}
        confirmLabel={t('pages.company.partner.dialogSubmit')}
        pending={submitMutation.isPending}
        error={submitMutation.error}
        message={validationError}
        onSubmit={handleSubmit}
      >
        <div className="flex flex-col gap-4">
          <div role="group" aria-label={t('pages.becomePartner.fields.kind')} className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">{t('pages.becomePartner.fields.kind')}</span>
            <div className="flex flex-wrap gap-2">
              {PARTNER_KINDS.map((k) => (
                <Button
                  key={k}
                  type="button"
                  size="sm"
                  variant={kind === k ? 'default' : 'outline'}
                  aria-pressed={kind === k}
                  className="rounded-full"
                  onClick={() => setKind(k)}
                >
                  {t(`pages.becomePartner.fields.kinds.${k}`)}
                </Button>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="partner-app-categories">{t('pages.becomePartner.fields.categoriesDescription')}</Label>
            <Textarea
              id="partner-app-categories"
              rows={3}
              placeholder={t('pages.becomePartner.fields.categoriesDescriptionPlaceholder')}
              value={categories}
              onChange={(e) => setCategories(e.target.value)}
            />
          </div>
        </div>
      </ActionDialog>
    </>
  );
}
