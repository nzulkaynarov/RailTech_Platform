import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronsUpDown, Plus } from 'lucide-react';

import { cn } from '@/lib/utils';
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
import { useManufacturers } from '@/hooks/useCatalog';

export interface ManufacturerFieldProps {
  /** Название бренда строкой — сервер нормализует (iexact) и создаст при отсутствии. */
  value: string;
  onChange: (name: string) => void;
  disabled?: boolean;
  id?: string;
  className?: string;
}

/**
 * Бренд/производитель: выбор из справочника ИЛИ свободный ввод (N1).
 *
 * До N1 здесь был `<Select>` по read-only справочнику, который никто не мог наполнить, —
 * вечное «—» без выхода. Паттерн Odoo «create on the fly» / Amazon brand: бренд — это
 * нормализуемый ввод продавца, не закрытый список. Значение — СТРОКА (`brand_name`);
 * сервер дедуплицирует без регистра тем же нормализатором, что Excel-импорт.
 *
 * Идиома — Popover + Command (как CountrySelect), чтобы поиск в системе был одним.
 */
export function ManufacturerField({ value, onChange, disabled, id, className }: ManufacturerFieldProps) {
  const { t } = useTranslation();
  const { data: manufacturers, isLoading } = useManufacturers({ fetchAll: true });
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  const options = manufacturers ?? [];
  const trimmed = query.trim();
  const exactExists = options.some((option) => option.name.toLowerCase() === trimmed.toLowerCase());

  const pick = (name: string) => {
    onChange(name);
    setQuery('');
    setOpen(false);
  };

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
          <span className={cn('truncate', !value && 'text-muted-foreground')}>
            {value || t('manufacturerField.placeholder')}
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command
          filter={(itemValue, search) => (itemValue.toLowerCase().includes(search.toLowerCase()) ? 1 : 0)}
        >
          <CommandInput
            placeholder={t('manufacturerField.searchPlaceholder')}
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <CommandEmpty>{t('manufacturerField.empty')}</CommandEmpty>
            <CommandGroup>
              {value && (
                <CommandItem value={`__clear ${value}`} onSelect={() => pick('')}>
                  <span className="text-muted-foreground">{t('manufacturerField.clear')}</span>
                </CommandItem>
              )}
              {options.map((option) => (
                <CommandItem key={option.id} value={option.name} onSelect={() => pick(option.name)}>
                  <Check
                    className={cn(
                      'mr-2 h-4 w-4',
                      value.toLowerCase() === option.name.toLowerCase() ? 'opacity-100' : 'opacity-0',
                    )}
                    aria-hidden="true"
                  />
                  <span className="truncate">{option.name}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
          {trimmed.length > 1 && !exactExists && (
            <div className="border-t p-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="w-full justify-start"
                onClick={() => pick(trimmed)}
              >
                <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
                {t('manufacturerField.create', { name: trimmed })}
              </Button>
            </div>
          )}
        </Command>
      </PopoverContent>
    </Popover>
  );
}
