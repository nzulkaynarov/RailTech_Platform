import { useEffect, useId, useRef, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { getBankByMfo } from '@/api/portal';
import {
  CURRENCIES,
  bankDraft,
  compact,
  type BankDraft,
  type BankErrors,
  type BankField,
  type BankPlace,
} from '@/lib/bankAccount';

/**
 * Поля банковского счёта (ADR-0029): место банка решает набор — в Узбекистане расчётный счёт и МФО, за рубежом IBAN или
 * номер, SWIFT/BIC, банк и посредник. Банк Узбекистана по МФО из справочника ЦБ подставляется и не правится (ERP при
 * сохранении всё равно берёт его из справочника); МФО, которого там нет, не тупик — предупреждение и банк вручную.
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
  const mfo = compact(value.mfo);
  const lookup = useQuery({
    queryKey: ['bank-directory', mfo],
    queryFn: () => getBankByMfo(mfo),
    enabled: !abroad && /^\d{5}$/.test(mfo),
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
  const known = !abroad && lookup.data?.bank?.mfo === mfo ? lookup.data.bank : null;
  const unknown = !abroad && /^\d{5}$/.test(mfo) && lookup.isSuccess && lookup.data.bank === null;
  // Что подставлено из справочника: при смене МФО на другой это уже не тот банк — убираем вместе с его SWIFT
  const filled = useRef<{ name: string; swift: string } | null>(null);
  useEffect(() => {
    if (!known || value.bank_name === known.name) return;
    filled.current = { name: known.name, swift: known.swift };
    onChange({ ...value, bank_name: known.name, swift: value.swift || known.swift });
  }, [known, value, onChange]);
  const setMfo = (next: string) => {
    const auto = filled.current;
    filled.current = null;
    onChange({
      ...value,
      mfo: next,
      ...(auto && value.bank_name === auto.name ? { bank_name: '' } : {}),
      ...(auto?.swift && value.swift === auto.swift ? { swift: '' } : {}),
    });
  };

  const field = (
    name: BankField,
    label: string,
    extra: { hint?: string; warning?: string; mono?: boolean; maxLength: number; readOnly?: boolean },
  ) => (
    <Field
      id={`${id}-${name}`}
      label={label}
      hint={extra.hint}
      warning={extra.warning}
      error={errors[name] ? t(`pages.company.bank.errors.${errors[name]}`) : undefined}
    >
      <Input
        id={`${id}-${name}`}
        value={value[name]}
        maxLength={extra.maxLength}
        disabled={disabled}
        readOnly={extra.readOnly}
        autoComplete="off"
        spellCheck={false}
        className={cn(extra.mono && 'font-mono', extra.readOnly && 'bg-muted')}
        aria-invalid={errors[name] ? true : undefined}
        aria-describedby={
          errors[name] || extra.warning || extra.hint
            ? `${id}-${name}-${errors[name] ? 'error' : extra.warning ? 'warning' : 'hint'}`
            : undefined
        }
        onChange={(event) => (name === 'mfo' ? setMfo(event.target.value) : set(name, event.target.value))}
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
          : field('mfo', t('pages.company.bank.mfo'), {
              mono: true,
              maxLength: 5,
              warning: unknown ? t('pages.company.bank.mfoNotInDirectory') : undefined,
            })}
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
        {field('bank_name', t('pages.company.bank.bankName'), {
          maxLength: 255,
          readOnly: Boolean(known),
          hint: abroad
            ? t('pages.company.bank.autoHint')
            : known
              ? t('pages.company.bank.fromDirectory')
              : unknown
                ? undefined
                : t('pages.company.bank.mfoFirst'),
        })}
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
  warning,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  warning?: string;
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
      ) : warning ? (
        <p id={`${id}-warning`} className="text-sm text-warning">
          {warning}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
