import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LogOut } from 'lucide-react';
import { toast } from '@/lib/toast';

import { apiErrorKey } from '@/api/errors';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAppMode } from '@/session/mode';
import { useLogout, useMe } from '@/session/useMe';

/**
 * Профиль: контакт и компания из `GET /me`, права, язык, выход. В Mini App выхода нет —
 * сессия привязана к Telegram и при следующем открытии вернётся сама (вход без страницы входа).
 */
export function ProfilePage() {
  const { t } = useTranslation();
  const mode = useAppMode();
  const me = useMe().data;
  const logout = useLogout();
  const navigate = useNavigate();

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
                <dd>{me.can_act ? t('profile.canAct') : t('profile.viewOnly')}</dd>
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
      </div>
    </>
  );
}
