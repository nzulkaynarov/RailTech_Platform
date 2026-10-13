import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronsUpDown } from 'lucide-react';

import { cn } from '@/lib/utils';
import { regionName } from '@/lib/regionName';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { useCountries } from '@/hooks/useMasterData';

export interface CountrySelectProps {
  /** id страны из справочника (строкой — так его хранят формы) либо пусто. */
  value: string | null | undefined;
  onChange: (countryId: string) => void;
  disabled?: boolean;
  placeholder?: string;
  id?: string;
  className?: string;
}

/**
 * Выбор страны из справочника ISO 3166-1 (249 записей).
 *
 * Почему поиск, а не `<Select>`: пока справочник состоял из семи торговых партнёров, простой
 * список работал. На полном перечне ISO выпадающий список без поиска — тупик: страну ищут
 * прокруткой, а названия ещё и на языке интерфейса. Идиома взята у выбора продавцов в
 * `CreateDealDialog` (Popover + Command), чтобы поведение поиска в системе было одним.
 *
 * Порядок — `sort_order` справочника (частые торговые партнёры вверху), затем название на
 * языке интерфейса. Поиск понимает и название, и код: менеджер ВЭД чаще помнит «DE», чем
 * «Германия», а копипаста из документа приносит именно код.
 */
export function CountrySelect({
  value,
  onChange,
  disabled,
  placeholder,
  id,
  className,
}: CountrySelectProps) {
  const { t, i18n } = useTranslation();
  const { data: countries, isLoading } = useCountries();
  const [open, setOpen] = useState(false);

  const options = useMemo(() => {
    const rows = (countries ?? []).map((country) => ({
      id: String(country.id),
      code: country.code,
      label: regionName(country.alpha2 || country.code, i18n.language, country.name),
      sortOrder: country.sort_order ?? 100,
    }));
    return rows.sort(
      (left, right) =>
        left.sortOrder - right.sortOrder || left.label.localeCompare(right.label, i18n.language),
    );
  }, [countries, i18n.language]);

  const selected = options.find((option) => option.id === String(value ?? ''));

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled || isLoading}
          className={cn('w-full justify-between font-normal', className)}
        >
          <span className={cn('truncate', !selected && 'text-muted-foreground')}>
            {selected ? selected.label : (placeholder ?? t('countrySelect.placeholder'))}
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command
          filter={(itemValue, search) =>
            itemValue.toLowerCase().includes(search.toLowerCase()) ? 1 : 0
          }
        >
          <CommandInput placeholder={t('countrySelect.searchPlaceholder')} />
          <CommandList>
            <CommandEmpty>{t('countrySelect.empty')}</CommandEmpty>
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option.id}
                  // В значение попадают и название, и код — поиск находит по обоим.
                  value={`${option.label} ${option.code}`}
                  onSelect={() => {
                    onChange(option.id);
                    setOpen(false);
                  }}
                >
                  <Check
                    className={cn(
                      'mr-2 h-4 w-4',
                      selected?.id === option.id ? 'opacity-100' : 'opacity-0',
                    )}
                    aria-hidden="true"
                  />
                  <span className="truncate">{option.label}</span>
                  <span className="ml-auto text-xs text-muted-foreground">{option.code}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
