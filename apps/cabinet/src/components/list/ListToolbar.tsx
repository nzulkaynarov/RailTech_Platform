import type { ReactNode } from 'react';
import { Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';

export interface ListToolbarOption<V extends string> {
  value: V;
  label: string;
}

/** Пунктов не больше стольких — кнопки-«пилюли»; больше — выпадающий список (в один ряд с поиском). */
export const PILLS_LIMIT = 4;

/** Radix Select не принимает пустое значение: «все» (`''`) в списке — служебный маркер. */
const ALL = '__all__';

/**
 * Единая панель списка: фильтр (кнопки до `PILLS_LIMIT` значений или выпадающий список) и поиск — в одном ряду;
 * на телефоне ряд переносится, поиск на всю ширину. `children` — дополнительные фильтры (даты) в том же ряду.
 * Значения фильтра — строки; «все» — тоже значение (`''`) в `options`.
 */
export function ListToolbar<V extends string>({
  filterLabel,
  options,
  value,
  onChange,
  search,
  display = 'auto',
  children,
  className,
}: {
  filterLabel?: string;
  options?: ListToolbarOption<V>[];
  value?: V;
  onChange?: (value: V) => void;
  /** `pills` — кнопки при любом числе значений (вкладки со счётчиками, которые должны быть видны сразу). */
  display?: 'auto' | 'pills';
  search?: { value: string; onChange: (value: string) => void; placeholder: string; label?: string };
  children?: ReactNode;
  className?: string;
}) {
  const asPills = options && (display === 'pills' || options.length <= PILLS_LIMIT);
  return (
    <div className={cn('mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center', className)} data-testid="list-toolbar">
      {options && asPills ? (
        <div role="group" aria-label={filterLabel} className="flex flex-wrap gap-2">
          {options.map((option) => (
            <Button
              key={option.value}
              type="button"
              size="sm"
              variant={option.value === value ? 'default' : 'outline'}
              aria-pressed={option.value === value}
              className="rounded-full"
              onClick={() => onChange?.(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      ) : null}
      {options && !asPills ? (
        <Select value={value || ALL} onValueChange={(next) => onChange?.((next === ALL ? '' : next) as V)}>
          <SelectTrigger aria-label={filterLabel} className="w-full sm:w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem key={option.value || ALL} value={option.value || ALL}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
      {children}
      {search ? (
        <div className="relative w-full sm:ml-auto sm:w-72">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={search.value}
            onChange={(event) => search.onChange(event.target.value)}
            placeholder={search.placeholder}
            aria-label={search.label ?? search.placeholder}
            className="pl-9"
          />
        </div>
      ) : null}
    </div>
  );
}
