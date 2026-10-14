import { useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Loader2, Send, UserPlus } from 'lucide-react';

import { crmBaseUrl, fetchFormToken, isCrmFormError, submitWebLead } from '@/api/crm';
import { botLink } from '@/app/links';
import { EmptyState } from '@/components/EmptyState';
import { TelegramLinkButton } from '@/components/TelegramLinkButton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import i18n from '@/i18n';
import {
  EMPTY_LEAD_FORM,
  LEAD_FORM_LIMITS,
  submitWithFreshToken,
  toWebLead,
  validateLeadForm,
  type LeadFormField,
  type LeadFormProblem,
  type LeadFormValues,
} from '@/lib/leadForm';
import { AuthLayout } from './AuthLayout';

/** Токен формы CRM — один на показ формы; обновляется только при `form_token_expired`/`invalid`. */
const FORM_TOKEN_KEY = ['crm', 'lead-form-token'] as const;
const FIELDS: LeadFormField[] = ['name', 'company', 'phone', 'email', 'text', 'consent'];

/** Ошибка CRM → проблема формы: код `details.reason` и поле, если CRM его назвала. */
function problemOf(error: unknown): LeadFormProblem {
  if (!isCrmFormError(error)) return { code: 'unknown', field: null };
  const field = FIELDS.find((name) => name === error.field) ?? null;
  if (i18n.exists(`newClient.errors.${error.code}`)) return { code: error.code, field };
  if (error.status === 422) return { code: 'validation_failed', field };
  return { code: error.status === 0 ? 'network' : 'unknown', field: null };
}

/**
 * «Я новый клиент» (ARCHITECTURE §17, M2-CAB-03): форма «Запрос» → лид CRM с источником `web`
 * (`GET /api/v1/leads/web/token` при показе, `POST /api/v1/leads/web` при отправке). Согласие на
 * обработку ПДн обязательно (DECISIONS Q-12), вложений нет — файлы клиент загрузит в кабинете после
 * приглашения. Рядом всегда «Написать в Telegram» (`start=web`). Адрес CRM не задан — только Telegram.
 */
export function NewClientPage() {
  const { t } = useTranslation();
  const telegramLink = botLink('web');
  const [sent, setSent] = useState(false);
  const formAvailable = crmBaseUrl() !== null;

  let body;
  if (sent) body = <SentCard telegramLink={telegramLink} />;
  else if (formAvailable) body = <LeadForm telegramLink={telegramLink} onSent={() => setSent(true)} />;
  else {
    body = (
      <>
        <h1 className="text-xl font-semibold">{t('newClient.title')}</h1>
        <EmptyState icon={UserPlus} title={t('newClient.unavailableTitle')} text={t('newClient.unavailableText')}>
          {telegramLink ? (
            <TelegramLinkButton href={telegramLink}>
              <Send aria-hidden="true" />
              {t('newClient.writeTelegram')}
            </TelegramLinkButton>
          ) : null}
        </EmptyState>
      </>
    );
  }

  return (
    <AuthLayout title={t('newClient.title')}>
      {body}
      <Button asChild variant="link" className="self-center">
        <Link to="/login">{t('newClient.backToLogin')}</Link>
      </Button>
    </AuthLayout>
  );
}

function LeadForm({ telegramLink, onSent }: { telegramLink: string | null; onSent: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const baseId = useId();
  const id = (field: string) => `${baseId}-${field}`;
  const errorId = id('error');
  const contactHintId = id('contact-hint');
  const [values, setValues] = useState<LeadFormValues>(EMPTY_LEAD_FORM);
  const [problem, setProblem] = useState<LeadFormProblem | null>(null);

  const token = useQuery({
    queryKey: FORM_TOKEN_KEY,
    queryFn: fetchFormToken,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const submit = useMutation({
    mutationFn: (form: LeadFormValues) => {
      if (!token.data) throw new Error('form token is not loaded');
      return submitWithFreshToken({
        build: (formToken) => toWebLead(form, i18n.resolvedLanguage, formToken),
        token: token.data,
        refreshToken: () => queryClient.fetchQuery({ queryKey: FORM_TOKEN_KEY, queryFn: fetchFormToken, staleTime: 0 }),
        submit: submitWebLead,
      });
    },
    onSuccess: onSent,
    onError: (error) => setProblem(problemOf(error)),
  });

  const set = <K extends keyof LeadFormValues>(field: K, value: LeadFormValues[K]) => {
    setValues((current) => ({ ...current, [field]: value }));
    if (problem?.field === field || (problem?.code === 'contact_required' && (field === 'phone' || field === 'email'))) {
      setProblem(null);
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const local = validateLeadForm(values);
    if (local) {
      setProblem(local);
      if (local.field) document.getElementById(id(local.field))?.focus();
      return;
    }
    setProblem(null);
    submit.mutate(values);
  };

  /** Поле с ошибкой: `aria-invalid` и ссылка на текст ошибки; «телефон или e-mail» — на оба поля. */
  const invalid = (field: LeadFormField) =>
    problem !== null && (problem.field === field || (problem.code === 'contact_required' && (field === 'phone' || field === 'email')));
  const describedBy = (field: LeadFormField, ...extra: string[]) =>
    [...extra, invalid(field) ? errorId : null].filter(Boolean).join(' ') || undefined;

  const tokenFailed = token.isError;
  const busy = submit.isPending;

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>
            <h1 className="text-xl">{t('newClient.title')}</h1>
          </CardTitle>
          <CardDescription>{t('newClient.intro')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate aria-describedby={problem ? errorId : undefined}>
            <div className="flex flex-col gap-2">
              <Label htmlFor={id('name')}>{t('newClient.form.name')}</Label>
              <Input
                id={id('name')}
                autoComplete="name"
                maxLength={LEAD_FORM_LIMITS.name}
                aria-required="true"
                value={values.name}
                onChange={(event) => set('name', event.target.value)}
                aria-invalid={invalid('name') || undefined}
                aria-describedby={describedBy('name')}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor={id('company')}>{t('newClient.form.company')}</Label>
              <Input
                id={id('company')}
                autoComplete="organization"
                maxLength={LEAD_FORM_LIMITS.company}
                value={values.company}
                onChange={(event) => set('company', event.target.value)}
              />
            </div>
            <fieldset className="flex flex-col gap-3">
              <legend className="mb-1 text-sm font-medium">{t('newClient.form.contacts')}</legend>
              <p id={contactHintId} className="text-xs text-muted-foreground">
                {t('newClient.form.contactsHint')}
              </p>
              <div className="flex flex-col gap-2">
                <Label htmlFor={id('phone')}>{t('newClient.form.phone')}</Label>
                <Input
                  id={id('phone')}
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  maxLength={LEAD_FORM_LIMITS.phone}
                  placeholder={t('newClient.form.phonePlaceholder')}
                  value={values.phone}
                  onChange={(event) => set('phone', event.target.value)}
                  aria-invalid={invalid('phone') || undefined}
                  aria-describedby={describedBy('phone', contactHintId)}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor={id('email')}>{t('newClient.form.email')}</Label>
                <Input
                  id={id('email')}
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  maxLength={LEAD_FORM_LIMITS.email}
                  placeholder={t('newClient.form.emailPlaceholder')}
                  value={values.email}
                  onChange={(event) => set('email', event.target.value)}
                  aria-invalid={invalid('email') || undefined}
                  aria-describedby={describedBy('email', contactHintId)}
                />
              </div>
            </fieldset>
            <div className="flex flex-col gap-2">
              <Label htmlFor={id('text')}>{t('newClient.form.text')}</Label>
              <Textarea
                id={id('text')}
                rows={4}
                maxLength={LEAD_FORM_LIMITS.text}
                aria-required="true"
                placeholder={t('newClient.form.textPlaceholder')}
                value={values.text}
                onChange={(event) => set('text', event.target.value)}
                aria-invalid={invalid('text') || undefined}
                aria-describedby={describedBy('text')}
              />
            </div>
            {/* Honeypot: невидим и недоступен с клавиатуры и для дикторов; заполнит только бот. */}
            <div aria-hidden="true" className="sr-only">
              <label htmlFor={id('website')}>{t('newClient.form.website')}</label>
              <input
                id={id('website')}
                name="website"
                type="text"
                tabIndex={-1}
                autoComplete="off"
                value={values.website}
                onChange={(event) => set('website', event.target.value)}
              />
            </div>
            <div className="flex items-start gap-3">
              <Checkbox
                id={id('consent')}
                className="mt-0.5"
                checked={values.consent}
                onCheckedChange={(checked) => set('consent', checked === true)}
                aria-required="true"
                aria-invalid={invalid('consent') || undefined}
                aria-describedby={describedBy('consent')}
              />
              <Label htmlFor={id('consent')} className="text-sm leading-snug font-normal">
                {t('newClient.form.consent')}
              </Label>
            </div>
            {problem ? (
              <Alert variant="destructive" id={errorId}>
                <AlertDescription>{t(`newClient.errors.${problem.code}`)}</AlertDescription>
              </Alert>
            ) : null}
            {tokenFailed ? (
              <Alert variant="destructive">
                <AlertDescription className="flex flex-col items-start gap-2">
                  {t('newClient.errors.tokenUnavailable')}
                  <Button type="button" size="sm" variant="outline" onClick={() => void token.refetch()}>
                    {t('common.retry')}
                  </Button>
                </AlertDescription>
              </Alert>
            ) : null}
            <Button type="submit" disabled={busy || !token.data}>
              {busy || token.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Send aria-hidden="true" />}
              {busy ? t('newClient.form.sending') : t('newClient.form.submit')}
            </Button>
          </form>
        </CardContent>
      </Card>
      {telegramLink ? (
        <div className="flex flex-col items-center gap-2 text-center">
          <p className="text-sm text-muted-foreground">{t('newClient.orTelegram')}</p>
          <TelegramLinkButton href={telegramLink} variant="outline">
            <Send aria-hidden="true" />
            {t('newClient.writeTelegram')}
          </TelegramLinkButton>
        </div>
      ) : null}
    </>
  );
}

function SentCard({ telegramLink }: { telegramLink: string | null }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col items-center gap-3 rounded-lg border bg-card px-4 py-8 text-center" aria-live="polite">
      <CheckCircle2 className="size-10 text-success" aria-hidden="true" />
      <h1 className="text-xl font-semibold">{t('newClient.sentTitle')}</h1>
      <p className="max-w-md text-sm text-muted-foreground">{t('newClient.sentText')}</p>
      {telegramLink ? (
        <TelegramLinkButton href={telegramLink}>
          <Send aria-hidden="true" />
          {t('newClient.writeTelegram')}
        </TelegramLinkButton>
      ) : null}
    </section>
  );
}
