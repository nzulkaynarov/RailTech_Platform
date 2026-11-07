import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Laptop, LogOut, Shield } from 'lucide-react';
import { toast } from '@/lib/toast';

import { apiErrorKey } from '@/api/errors';
import { useRevokeOtherSessions, useSessions } from '@/api/queries';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { PageHeader } from '@/components/PageHeader';
import { ToneBadge } from '@/components/StatusBadge';
import type { ConnectTelegramState } from '@/onboarding/telegramStep';
import { TelegramNotifications } from '@/components/TelegramNotifications';
import { NotificationSettingsCard } from '@/components/NotificationSettingsCard';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatDateTime } from '@/lib/format';
import { useAppMode } from '@/session/mode';
import { useLogout, useMe } from '@/session/useMe';

/**
 * Профиль: контакт и компания из `GET /me`, права, язык, выход, «Уведомления» (Telegram, ADR-0023 п. 3). В Mini App
 * выхода нет — сессия привязана к Telegram и при следующем открытии вернётся сама (вход без страницы входа).
 * `/profile#notifications` (ссылка из писем и плашки) прокручивает к «Уведомлениям».
 */
export function ProfilePage() {
  const { t } = useTranslation();
  const mode = useAppMode();
  const me = useMe().data;
  const logout = useLogout();
  const navigate = useNavigate();
  const location = useLocation();
  const autoStart = (location.state as Partial<ConnectTelegramState> | null)?.connectTelegram === true;

  useEffect(() => {
    if (location.hash !== '#notifications') return;
    document.getElementById('notifications')?.scrollIntoView?.({ block: 'start' });
  }, [location.hash, me]);

  if (!me) return null;
  const { contact, company } = me;

  const onLogout = () =>
    logout.mutate(undefined, {
      onSuccess: () => navigate('/login', { replace: true }),
      onError: (error) => {
        toast.error(t(apiErrorKey(error)));
        navigate('/login', { replace: true });
      },
    });

  return (
    <>
      <PageHeader title={t('profile.title')} />
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>
              <h2 className="text-base">{t('profile.contact')}</h2>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-3 text-sm">
              <div>
                <dt className="text-muted-foreground">{t('profile.name')}</dt>
                <dd className="font-medium break-words">{contact.name}</dd>
              </div>
              {contact.email ? (
                <div>
                  <dt className="text-muted-foreground">{t('profile.email')}</dt>
                  <dd className="break-all">{contact.email}</dd>
                </div>
              ) : null}
              {contact.phone ? (
                <div>
                  <dt className="text-muted-foreground">{t('profile.phone')}</dt>
                  <dd>{contact.phone}</dd>
                </div>
              ) : null}
              <div>
                <dt className="text-muted-foreground">{t('profile.company')}</dt>
                <dd className="break-words">{company.name}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t('profile.authMethod')}</dt>
                <dd>{t(`profile.authMethods.${me.auth_method}`)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t('profile.rights')}</dt>
                <dd className="flex flex-wrap items-center gap-2">
                  <span>{me.can_act ? t('profile.canAct') : t('profile.viewOnly')}</span>
                  {contact.is_admin ? <ToneBadge tone="warning">{t('profile.admin')}</ToneBadge> : null}
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>
              <h2 className="text-base">{t('profile.language')}</h2>
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <LanguageSwitcher />
            {mode === 'web' ? (
              <Button variant="outline" className="self-start" onClick={onLogout} disabled={logout.isPending}>
                <LogOut aria-hidden="true" />
                {t('profile.logout')}
              </Button>
            ) : null}
          </CardContent>
        </Card>
        <TelegramNotifications autoStart={autoStart} />
        <NotificationSettingsCard />
        <SessionsCard />
      </div>
    </>
  );
}

function SessionsCard() {
  const { t } = useTranslation();
  const sessions = useSessions();
  const revokeOthers = useRevokeOtherSessions();

  const handleRevokeOthers = () => {
    revokeOthers.mutate(undefined, {
      onSuccess: (data) => {
        toast.success(t('profile.sessions.revoked', { count: data.revoked_count }));
      },
      onError: (err) => {
        toast.error(t(apiErrorKey(err)));
      },
    });
  };

  const otherSessionsCount = sessions.data ? sessions.data.filter((s) => !s.is_current).length : 0;

  return (
    <Card className="md:col-span-2">
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>
            <h2 className="text-base flex items-center gap-2">
              <Shield className="size-4 text-primary" aria-hidden="true" />
              {t('profile.sessions.title')}
            </h2>
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-1">
            {t('profile.sessions.desc')}
          </p>
        </div>
        {otherSessionsCount > 0 ? (
          <Button
            size="sm"
            variant="outline"
            disabled={revokeOthers.isPending}
            onClick={handleRevokeOthers}
          >
            {t('profile.sessions.revokeOthers')}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {sessions.isPending ? (
          <p className="text-xs text-muted-foreground">{t('app.loading')}</p>
        ) : sessions.isError ? (
          <p className="text-xs text-destructive">{t(apiErrorKey(sessions.error))}</p>
        ) : sessions.data.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t('profile.sessions.noOther')}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {sessions.data.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                <div className="flex items-center gap-3">
                  <div className="size-8 rounded-full bg-muted flex items-center justify-center text-muted-foreground">
                    <Laptop className="size-4" aria-hidden="true" />
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{s.user_agent || t('profile.sessions.device')}</span>
                      {s.is_current ? (
                        <ToneBadge tone="success">{t('profile.sessions.current')}</ToneBadge>
                      ) : null}
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {s.ip_address ? `${s.ip_address} • ` : ''}
                      {t('profile.sessions.lastUsed', { date: formatDateTime(s.last_used_at) })}
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
