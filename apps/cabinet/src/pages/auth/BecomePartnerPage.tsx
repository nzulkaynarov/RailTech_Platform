import { useId, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { CheckCircle2, Handshake, Loader2, ShieldCheck, FileCheck, Store } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import { submitPartnerApplication, type PartnerKind, type Schemas } from '@/api/portal';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { LOCALES } from '@/i18n/locales';
import { COUNTRIES, DEFAULT_COUNTRY, adaptPhoneForCountry, findCountry, type CountryInfo } from '@/lib/countries';
import { AuthLayout } from './AuthLayout';

interface FormValues {
  company_name: string;
  inn: string;
  kind: PartnerKind;
  categories_description: string;
  contact_name: string;
  email: string;
  phone: string;
  language: Schemas['Language'];
  consent: boolean;
  website: string;
}

const KINDS: PartnerKind[] = ['supplier', 'manufacturer', 'principal', 'other'];

/**
 * Публичная воронка «Стать партнёром» (ADR-0022, DECISIONS 2026-11-05, PART-ONBOARD-1).
 * Поставщики и производители подают заявку на заключение партнёрского договора.
 * Защищена honeypot-полем (website) и ограничением частоты запросов на бэкенде.
 */
export function BecomePartnerPage() {
  const { t, i18n } = useTranslation();
  const id = useId();
  const [searchParams] = useSearchParams();
  const initialEmail = searchParams.get('email') ?? '';
  const defaultLang = (LOCALES.find((l) => l.code === i18n.language)?.code ?? 'ru') as Schemas['Language'];

  const [selectedCountry, setSelectedCountry] = useState<CountryInfo>(DEFAULT_COUNTRY);
  const [values, setValues] = useState<FormValues>({
    company_name: '',
    inn: '',
    kind: 'supplier',
    categories_description: '',
    contact_name: '',
    email: initialEmail,
    phone: '',
    language: defaultLang,
    consent: false,
    website: '',
  });
  const [validationError, setValidationError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: submitPartnerApplication,
  });

  const handleCountryChange = (newCode: string) => {
    const nextCountry = findCountry(newCode);
    const updatedPhone = adaptPhoneForCountry(values.phone, selectedCountry, nextCountry);
    setSelectedCountry(nextCountry);
    setValues((prev) => ({
      ...prev,
      phone: updatedPhone,
    }));
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setValidationError(null);

    if (!values.company_name.trim()) {
      setValidationError(t('pages.becomePartner.errors.companyNameRequired'));
      return;
    }
    if (!values.contact_name.trim()) {
      setValidationError(t('pages.becomePartner.errors.contactNameRequired'));
      return;
    }
    if (!values.email.trim() || !values.email.includes('@')) {
      setValidationError(t('pages.becomePartner.errors.emailInvalid'));
      return;
    }
    if (values.categories_description.trim().length < 10) {
      setValidationError(t('pages.becomePartner.errors.categoriesDescriptionTooShort'));
      return;
    }
    if (!values.consent) {
      setValidationError(t('apiErrors.CONSENT_REQUIRED'));
      return;
    }

    const isUz = selectedCountry.isUzbekistan;
    const taxValue = values.inn.trim();

    mutation.mutate({
      company_name: values.company_name.trim(),
      country: selectedCountry.code === 'OTHER' ? undefined : selectedCountry.code,
      inn: isUz && taxValue ? taxValue : undefined,
      registration_number: !isUz && taxValue ? taxValue : undefined,
      kind: values.kind,
      categories_description: values.categories_description.trim(),
      contact_name: values.contact_name.trim(),
      email: values.email.trim().toLowerCase(),
      phone: values.phone.trim() || undefined,
      language: values.language,
      consent: values.consent,
      website: values.website,
    });
  };

  const activeError = validationError || (mutation.error ? t(apiErrorKey(mutation.error)) : null);

  return (
    <AuthLayout title={t('pages.becomePartner.title')}>
      {mutation.isSuccess ? (
        <Card className="border-border shadow-sm">
          <CardHeader className="text-center">
            <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-accent text-primary">
              <CheckCircle2 className="size-8" aria-hidden="true" />
            </div>
            <CardTitle>
              <h1 className="mt-2 text-xl font-semibold">{t('pages.becomePartner.successTitle')}</h1>
            </CardTitle>
            <CardDescription>{t('pages.becomePartner.successSubtitle')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
              <h2 className="text-sm font-semibold">{t('pages.becomePartner.nextStepsTitle')}</h2>
              <ul className="flex flex-col gap-3 text-sm text-muted-foreground">
                <li className="flex items-start gap-3">
                  <ShieldCheck className="size-5 shrink-0 text-primary" aria-hidden="true" />
                  <div>
                    <p className="font-medium text-foreground">{t('pages.becomePartner.step1Title')}</p>
                    <p className="text-xs">{t('pages.becomePartner.step1Desc')}</p>
                  </div>
                </li>
                <li className="flex items-start gap-3">
                  <FileCheck className="size-5 shrink-0 text-primary" aria-hidden="true" />
                  <div>
                    <p className="font-medium text-foreground">{t('pages.becomePartner.step2Title')}</p>
                    <p className="text-xs">{t('pages.becomePartner.step2Desc')}</p>
                  </div>
                </li>
                <li className="flex items-start gap-3">
                  <Store className="size-5 shrink-0 text-primary" aria-hidden="true" />
                  <div>
                    <p className="font-medium text-foreground">{t('pages.becomePartner.step3Title')}</p>
                    <p className="text-xs">{t('pages.becomePartner.step3Desc')}</p>
                  </div>
                </li>
              </ul>
            </div>
            <Button asChild className="w-full">
              <Link to="/login">{t('pages.becomePartner.backToLogin')}</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="border-border shadow-sm">
          <CardHeader>
            <div className="flex items-center gap-2">
              <Handshake className="size-6 text-primary" aria-hidden="true" />
              <CardTitle>
                <h1 className="text-xl font-semibold">{t('pages.becomePartner.title')}</h1>
              </CardTitle>
            </div>
            <CardDescription>{t('pages.becomePartner.subtitle')}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
              {/* Honeypot поле (скрыто от пользователей, видимо для ботов) */}
              <div className="absolute -left-[9999px] top-auto h-0 w-0 overflow-hidden opacity-0" aria-hidden="true">
                <label htmlFor={`${id}-website`}>Website</label>
                <input
                  id={`${id}-website`}
                  type="text"
                  name="website"
                  tabIndex={-1}
                  autoComplete="off"
                  value={values.website}
                  onChange={(e) => setValues({ ...values, website: e.target.value })}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-country`}>{t('pages.becomePartner.fields.country')}</Label>
                <Select value={selectedCountry.code} onValueChange={handleCountryChange}>
                  <SelectTrigger id={`${id}-country`} className="w-full">
                    <SelectValue placeholder={t('countryMask.countryPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent position="popper">
                    {COUNTRIES.map((c) => (
                      <SelectItem key={c.code} value={c.code}>
                        {c.name} ({c.phoneCode})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-company-name`}>{t('pages.becomePartner.fields.companyName')}</Label>
                <Input
                  id={`${id}-company-name`}
                  required
                  placeholder={t('pages.becomePartner.fields.companyNamePlaceholder')}
                  value={values.company_name}
                  onChange={(e) => setValues({ ...values, company_name: e.target.value })}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-inn`}>
                  {selectedCountry.isUzbekistan
                    ? t('pages.becomePartner.fields.inn')
                    : t(selectedCountry.taxLabelKey, selectedCountry.taxLabelDefault)}
                </Label>
                <Input
                  id={`${id}-inn`}
                  placeholder={selectedCountry.taxPlaceholder}
                  value={values.inn}
                  onChange={(e) => setValues({ ...values, inn: e.target.value })}
                />
              </div>

              <div role="group" aria-label={t('pages.becomePartner.fields.kind')} className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">{t('pages.becomePartner.fields.kind')}</span>
                <div className="flex flex-wrap gap-2">
                  {KINDS.map((kind) => (
                    <Button
                      key={kind}
                      type="button"
                      size="sm"
                      variant={values.kind === kind ? 'default' : 'outline'}
                      aria-pressed={values.kind === kind}
                      className="rounded-full"
                      onClick={() => setValues({ ...values, kind })}
                    >
                      {t(`pages.becomePartner.fields.kinds.${kind}`)}
                    </Button>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-categories`}>{t('pages.becomePartner.fields.categoriesDescription')}</Label>
                <Textarea
                  id={`${id}-categories`}
                  required
                  rows={3}
                  placeholder={t('pages.becomePartner.fields.categoriesDescriptionPlaceholder')}
                  value={values.categories_description}
                  onChange={(e) => setValues({ ...values, categories_description: e.target.value })}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-contact-name`}>{t('pages.becomePartner.fields.contactName')}</Label>
                <Input
                  id={`${id}-contact-name`}
                  required
                  placeholder={t('pages.becomePartner.fields.contactNamePlaceholder')}
                  value={values.contact_name}
                  onChange={(e) => setValues({ ...values, contact_name: e.target.value })}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-email`}>{t('pages.becomePartner.fields.email')}</Label>
                <Input
                  id={`${id}-email`}
                  type="email"
                  inputMode="email"
                  required
                  placeholder={t('pages.becomePartner.fields.emailPlaceholder')}
                  value={values.email}
                  onChange={(e) => setValues({ ...values, email: e.target.value })}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-phone`}>{t('pages.becomePartner.fields.phone')}</Label>
                <Input
                  id={`${id}-phone`}
                  type="tel"
                  placeholder={selectedCountry.phonePlaceholder}
                  value={values.phone}
                  onChange={(e) => setValues({ ...values, phone: e.target.value })}
                />
              </div>

              <div role="group" aria-label={t('pages.becomePartner.fields.language')} className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">{t('pages.becomePartner.fields.language')}</span>
                <div className="flex flex-wrap gap-2">
                  {LOCALES.map((locale) => (
                    <Button
                      key={locale.code}
                      type="button"
                      size="sm"
                      variant={values.language === locale.code ? 'default' : 'outline'}
                      aria-pressed={values.language === locale.code}
                      className="rounded-full"
                      onClick={() => setValues({ ...values, language: locale.code })}
                    >
                      {locale.nativeName}
                    </Button>
                  ))}
                </div>
              </div>

              <div className="flex items-start gap-2 pt-2">
                <Checkbox
                  id={`${id}-consent`}
                  checked={values.consent}
                  onCheckedChange={(checked) => setValues({ ...values, consent: checked === true })}
                />
                <Label htmlFor={`${id}-consent`} className="text-xs leading-normal font-normal text-muted-foreground">
                  {t('pages.becomePartner.fields.consent')}
                </Label>
              </div>

              {activeError ? (
                <Alert variant="destructive">
                  <AlertDescription>{activeError}</AlertDescription>
                </Alert>
              ) : null}

              <Button type="submit" disabled={mutation.isPending} className="mt-2 w-full">
                {mutation.isPending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                    {t('pages.becomePartner.submitting')}
                  </>
                ) : (
                  t('pages.becomePartner.submit')
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      {!mutation.isSuccess ? (
        <Button asChild variant="link" className="self-center">
          <Link to="/login">{t('pages.becomePartner.backToLogin')}</Link>
        </Button>
      ) : null}
    </AuthLayout>
  );
}
