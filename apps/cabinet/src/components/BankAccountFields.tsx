import { useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { CURRENCIES, bankDraft, type BankDraft, type BankErrors, type BankField, type BankPlace } from '@/lib/bankAccount';

/**
 * Поля банковского счёта (ADR-0029): место банка решает набор — в Узбекистане расчётный счёт и МФО, за рубежом IBAN или
 * номер, SWIFT/BIC, банк и посредник. Название банка и SWIFT для Узбекистана ERP подставит по МФО, за рубежом — по IBAN.
 */
export function BankAccountFields({
  value,
  errors,
  disabled,
  onChange,
}: {
  value: BankDraft;
  errors: BankErrors;
  disabled?: boolean;
  onChange: (next: BankDraft) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const set = (field: BankField, next: string) => onChange({ ...value, [field]: next });
  const abroad = value.place === 'abroad';

  const field = (name: BankField, label: string, extra: { hint?: string; mono?: boolean; maxLength: number }) => (
    <Field
      id={`${id}-${name}`}
      label={label}
      hint={extra.hint}
      error={errors[name] ? t(`pages.company.bank.errors.${errors[name]}`) : undefined}
    >
      <Input
        id={`${id}-${name}`}
        value={value[name]}
        maxLength={extra.maxLength}
        disabled={disabled}
        autoComplete="off"
        spellCheck={false}
        className={extra.mono ? 'font-mono' : undefined}
        aria-invalid={errors[name] ? true : undefined}
        aria-describedby={errors[name] ? `${id}-${name}-error` : extra.hint ? `${id}-${name}-hint` : undefined}
        onChange={(event) => set(name, event.target.value)}
      />
    </Field>
  );

  return (
    <fieldset className="flex flex-col gap-3" disabled={disabled}>
      <div role="group" aria-label={t('pages.company.bank.place')} className="flex flex-wrap gap-2">
        {(['uz', 'abroad'] as BankPlace[]).map((place) => (
          <Button
            key={place}
            type="button"
            size="sm"
            variant={value.place === place ? 'default' : 'outline'}
            aria-pressed={value.place === place}
            className="rounded-full"
            onClick={() => onChange(place === value.place ? value : { ...bankDraft(), currency: value.currency, place })}
          >
            {t(`pages.company.bank.places.${place}`)}
          </Button>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id={`${id}-currency`} label={t('pages.company.bank.currency')}>
          <Select value={value.currency} onValueChange={(next) => set('currency', next)} disabled={disabled}>
            <SelectTrigger id={`${id}-currency`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper">
              {CURRENCIES.map((code) => (
                <SelectItem key={code} value={code}>
                  {code}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {abroad
          ? field('swift', t('pages.company.bank.swift'), { mono: true, maxLength: 11, hint: t('pages.company.bank.swiftHint') })
          : field('mfo', t('pages.company.bank.mfo'), { mono: true, maxLength: 5 })}
      </div>
      {abroad
        ? field('holder_name_latin', t('pages.company.bank.holderLatin'), {
            maxLength: 140,
            hint: t('pages.company.bank.holderLatinHint'),
          })
        : null}
      {field('account', t(abroad ? 'pages.company.bank.iban' : 'pages.company.bank.account'), {
        mono: true,
        maxLength: abroad ? 42 : 24,
        hint: t(abroad ? 'pages.company.bank.ibanHint' : 'pages.company.bank.accountHint'),
      })}
      <div className="grid gap-3 sm:grid-cols-2">
        {field('bank_name', t('pages.company.bank.bankName'), { maxLength: 255, hint: t('pages.company.bank.autoHint') })}
        {abroad
          ? field('bank_address', t('pages.company.bank.bankAddress'), { maxLength: 255 })
          : field('swift', t('pages.company.bank.swiftOptional'), { mono: true, maxLength: 11 })}
      </div>
      {abroad ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {field('intermediary_swift', t('pages.company.bank.intermediarySwift'), { mono: true, maxLength: 11 })}
          {field('intermediary_account', t('pages.company.bank.intermediaryAccount'), { mono: true, maxLength: 50 })}
        </div>
      ) : null}
    </fieldset>
  );
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
