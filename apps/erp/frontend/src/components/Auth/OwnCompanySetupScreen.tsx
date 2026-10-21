import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { isAxiosError } from 'axios';
import { Building2, Loader2, AlertCircle, LogOut } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { setupApi, type OwnCompanyInput } from '@/api/setupApi';
import { translateApiError } from '@/lib/apiError';
import { useAuthStore } from '@/store/authStore';

type FieldName = keyof OwnCompanyInput;
const FIELDS: FieldName[] = ['name', 'inn', 'legal_address', 'phone', 'email'];

/**
 * Мастер первого запуска ERP (FIX-65): «Настройка ERP: ваша компания».
 *
 * Показывается администратору (суперпользователю), когда своей компании ещё нет. Раньше здесь был
 * тупик «обратитесь к администратору», а компанию заводили руками в `manage.py shell`. Обязательно
 * только название; остальное правится позже в «Настройки → Реквизиты». Ошибки полей приходят от
 * сервера (422) и показываются у поля; после успеха перечитываем профиль — App входит в приложение.
 */
export function OwnCompanySetupScreen() {
  const { t } = useTranslation();
  const logout = useAuthStore((s) => s.logout);
  const initAuth = useAuthStore((s) => s.initAuth);
  const [values, setValues] = useState<Record<FieldName, string>>({
    name: '',
    inn: '',
    legal_address: '',
    phone: '',
    email: '',
  });
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FieldName, string>>>({});
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const set = (name: FieldName) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setValues((v) => ({ ...v, [name]: e.target.value }));

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    const errors: Partial<Record<FieldName, string>> = {};
    if (!values.name.trim()) errors.name = t('setup.company.errors.nameRequired');
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;

    setSubmitting(true);
    try {
      await setupApi.createOwnCompany({
        name: values.name.trim(),
        inn: values.inn.trim(),
        legal_address: values.legal_address.trim(),
        phone: values.phone.trim(),
        email: values.email.trim(),
      });
      await initAuth();
    } catch (err) {
      if (isAxiosError(err) && err.response?.status === 422 && err.response.data) {
        const data = err.response.data as Record<string, string[] | string>;
        const next: Partial<Record<FieldName, string>> = {};
        for (const name of FIELDS) {
          const msg = data[name];
          if (msg) next[name] = Array.isArray(msg) ? msg.join(' ') : String(msg);
        }
        setFieldErrors(next);
        if (!Object.keys(next).length) setFormError(translateApiError(err));
      } else {
        setFormError(translateApiError(err));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const field = (name: FieldName, props: React.ComponentProps<typeof Input> = {}) => {
    const error = fieldErrors[name];
    return (
      <div className="space-y-2">
        <Label htmlFor={`setup-${name}`}>
          {t(`setup.company.fields.${name}`)}
          {name === 'name' && <span aria-hidden="true"> *</span>}
        </Label>
        <Input
          id={`setup-${name}`}
          value={values[name]}
          onChange={set(name)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `setup-${name}-error` : undefined}
          required={name === 'name'}
          {...props}
        />
        {error && (
          <p id={`setup-${name}-error`} role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </div>
    );
  };

  return (
    <main className="min-h-screen bg-background flex items-center justify-center p-4 sm:p-6">
      <Card className="w-full max-w-lg">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-14 w-14 items-center justify-center rounded-full bg-muted">
            <Building2 className="h-7 w-7 text-muted-foreground" aria-hidden="true" />
          </div>
          <CardTitle className="text-xl">
            <h1>{t('setup.company.title')}</h1>
          </CardTitle>
          <CardDescription>{t('setup.company.hint')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} noValidate className="space-y-4">
            {field('name', { autoComplete: 'organization', autoFocus: true })}
            {field('inn', { inputMode: 'numeric', autoComplete: 'off' })}
            {field('legal_address', { autoComplete: 'street-address' })}
            <div className="grid gap-4 sm:grid-cols-2">
              {field('phone', { type: 'tel', autoComplete: 'tel' })}
              {field('email', { type: 'email', autoComplete: 'email' })}
            </div>
            <p className="text-sm text-muted-foreground">{t('setup.company.later')}</p>

            {formError && (
              <Alert variant="destructive">
                <AlertCircle className="size-4" />
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}

            <div className="flex flex-col gap-2 sm:flex-row-reverse">
              <Button type="submit" size="lg" disabled={submitting} className="sm:flex-1">
                {submitting && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                {t('setup.company.submit')}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="lg"
                className="gap-2"
                onClick={async () => {
                  await logout();
                  window.location.assign('/');
                }}
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
                {t('auth.noCompany.logout')}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
