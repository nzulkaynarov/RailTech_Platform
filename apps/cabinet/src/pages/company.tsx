import { useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Building2, Loader2, Pencil, Save, UserPlus, Users } from 'lucide-react';
import { toast } from '@/lib/toast';

import { apiErrorKey } from '@/api/errors';
import type { Company, CompanyUpdate, Schemas, TeamInvite, TeamMember } from '@/api/portal';
import { useCompany, useInviteTeamMember, useTeam, useUpdateCompany } from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
import { DetailList } from '@/components/Details';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { UnsavedChangesBar } from '@/components/UnsavedChangesBar';
import { DetailSkeleton, ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ToneBadge } from '@/components/StatusBadge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { LOCALES } from '@/i18n/locales';
import { companyChanges, validateInvite, type InviteDraft, type InviteProblem } from '@/lib/company';
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
  const [editing, setEditing] = useState(false);

  return (
    <>
      <PageHeader
        title={t('pages.company.title')}
        icon={Building2}
        actions={
          company.data && !editing ? (
            <CanAct>
              <Button variant="outline" onClick={() => setEditing(true)}>
                <Pencil aria-hidden="true" />
                {t('pages.company.edit')}
              </Button>
            </CanAct>
          ) : null
        }
      />
      {company.isPending ? (
        <DetailSkeleton />
      ) : company.isError ? (
        <ErrorState error={company.error} onRetry={() => void company.refetch()} />
      ) : editing ? (
        <CompanyForm company={company.data} onDone={() => setEditing(false)} />
      ) : (
        <div className="flex flex-col gap-4">
          <Card>
            <CardContent>
              <DetailList
                className="sm:grid-cols-1"
                items={[
                  { label: t('pages.company.fields.name'), value: company.data.name },
                  { label: t('pages.company.fields.inn'), value: company.data.inn || t('pages.company.notSet') },
                  { label: t('pages.company.fields.legalAddress'), value: company.data.legal_address || t('pages.company.notSet') },
                  {
                    label: t('pages.company.fields.bankDetails'),
                    value: <span className="whitespace-pre-line">{company.data.bank_details || t('pages.company.notSet')}</span>,
                  },
                  { label: t('pages.company.fields.language'), value: t(`languages.${company.data.language}`) },
                ]}
              />
            </CardContent>
          </Card>
          <Button asChild variant="outline" className="self-start">
            <Link to="/team">
              <Users aria-hidden="true" />
              {t('pages.company.toTeam')}
            </Link>
          </Button>
        </div>
      )}
    </>
  );
}

function CompanyForm({ company, onDone }: { company: Company; onDone: () => void }) {
  const { t } = useTranslation();
  const id = useId();
  const update = useUpdateCompany();
  const [draft, setDraft] = useState<Required<CompanyUpdate>>({
    name: company.name,
    inn: company.inn ?? '',
    legal_address: company.legal_address ?? '',
    bank_details: company.bank_details ?? '',
    language: company.language,
  });
  const [nameMissing, setNameMissing] = useState(false);

  const set = <K extends keyof CompanyUpdate>(key: K, value: Required<CompanyUpdate>[K]) =>
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

  const reset = () => {
    setDraft({
      name: company.name,
      inn: company.inn ?? '',
      legal_address: company.legal_address ?? '',
      bank_details: company.bank_details ?? '',
      language: company.language,
    });
    setNameMissing(false);
  };

  return (
    <>
      <UnsavedChangesBar
        dirty={isDirty}
        onSave={() => submit({ preventDefault: () => {} } as FormEvent)}
        onReset={reset}
        pending={update.isPending}
      />
      <Card>
        <CardContent>
          <form onSubmit={submit} noValidate className="flex flex-col gap-4">
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
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-inn`}>{t('pages.company.fields.inn')}</Label>
            <Input id={`${id}-inn`} inputMode="numeric" value={draft.inn} maxLength={20} onChange={(event) => set('inn', event.target.value)} />
          </div>
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
            <Label htmlFor={`${id}-bank`}>{t('pages.company.fields.bankDetails')}</Label>
            <Textarea
              id={`${id}-bank`}
              rows={3}
              value={draft.bank_details}
              maxLength={1000}
              onChange={(event) => set('bank_details', event.target.value)}
            />
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
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={onDone} disabled={update.isPending}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
              {t('common.save')}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
    </>
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

// --- команда ----------------------------------------------------------------------------------

export function TeamPage() {
  const { t } = useTranslation();
  const team = useTeam();
  const meId = useMe().data?.contact.id;
  const [inviting, setInviting] = useState(false);

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
              <MemberCard member={member} isMe={member.id === meId} />
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-xs text-muted-foreground">{t('pages.team.rightsHint')}</p>
      <InviteDialog open={inviting} onOpenChange={setInviting} />
    </>
  );
}

function MemberCard({ member, isMe }: { member: TeamMember; isMe: boolean }) {
  const { t } = useTranslation();
  return (
    <article className="notion-card flex h-full min-w-0 flex-col gap-3 rounded-2xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold break-words">{member.name}</h2>
        {isMe ? <ToneBadge tone="info">{t('pages.team.you')}</ToneBadge> : null}
        {member.is_primary ? <ToneBadge tone="neutral">{t('pages.team.primary')}</ToneBadge> : null}
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

function InviteDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const invite = useInviteTeamMember();
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
            placeholder="+998"
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
      </div>
    </ActionDialog>
  );
}
