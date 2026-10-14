import { useTranslation } from 'react-i18next';
import { Building2, LogOut } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/store/authStore';

/**
 * Учётная запись вошла, но не привязана ни к одной компании.
 *
 * Раньше здесь была форма «создайте компанию» (саморегистрация, `auth/submit-profile`). В ERP
 * её нет (M1-ERP-02): сотрудников заводит CRM (ADR-0003) или приглашает коллега, контрагента —
 * бэк-офис. Поэтому экран не предлагает действия, которого нет, а говорит, к кому идти.
 */
export function NoCompanyScreen() {
  const { t } = useTranslation();
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-14 w-14 items-center justify-center rounded-full bg-muted">
            <Building2 className="h-7 w-7 text-muted-foreground" aria-hidden="true" />
          </div>
          <CardTitle className="text-xl">{t('auth.noCompany.title')}</CardTitle>
          <CardDescription>{t('auth.noCompany.hint')}</CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center">
          <Button
            variant="outline"
            className="gap-2"
            onClick={async () => {
              await logout();
              window.location.assign('/');
            }}
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            {t('auth.noCompany.logout')}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
