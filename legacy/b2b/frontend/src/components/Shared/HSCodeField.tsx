import { useEffect, useId, useRef, useState } from 'react';
import { formatHSCode, leafName, MIN_QUERY_LENGTH } from '@/lib/hsCode';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useHSCodeSuggest, useHSCodeValidation } from '@/hooks/useCatalog';

/**
 * Поле кода ТН ВЭД с автокомплитом по справочнику и МЯГКОЙ валидацией (волна T1).
 *
 * Паттерн Shopify: HS-поле — это автокомплит В МЕСТЕ РАБОТЫ, а не «сходи в справочник и
 * найди». Печатаешь ТЕКСТ («подшип…») — выпадают кандидаты из классификатора ГТК (13 тыс.
 * кодов) с собственным именем позиции; печатаешь ЦИФРЫ — ветка кодов с иерархией. Выбор
 * фиксирует код.
 *
 * До T1 система требовала то, что негде ввести: очередь номенклатуры писала «не хватает: Код
 * ТН ВЭД», а в форме карточки поля не было вовсе — единственным местом ввода была строка КП
 * со свободным текстом.
 *
 * Свободный ввод ОСТАЁТСЯ: справочник может быть пуст (прод до первого синка), а код известен
 * продавцу из декларации. Валидация только подсвечивает (PRODUCT RULE 2 — не блокируем):
 * «нет в справочнике» / «выведен из редакции» — жёлтая пометка, не ошибка.
 *
 * Идиома — ProductNameCell (тот же Popover+Input+debounce), поэтому компонент работает и в
 * просторной форме карточки, и в тесной ячейке грида КП.
 */
export interface HSCodeFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** Компактный режим ячейки грида (h-8, узкая ширина). */
  dense?: boolean;
  placeholder?: string;
  className?: string;
  'aria-invalid'?: boolean;
  title?: string;
}

export function HSCodeField({ value, onChange, dense = false, placeholder, className, ...rest }: HSCodeFieldProps) {
  const { t } = useTranslation();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  // Подсказки — по НАБИРАЕМОМУ тексту; после выбора кандидата запрос гасится, чтобы список
  // не переоткрывался поверх только что выбранного кода.
  const [query, setQuery] = useState('');
  const debounced = useDebouncedValue(query, 250);

  const { data: candidates } = useHSCodeSuggest(debounced.length >= MIN_QUERY_LENGTH ? debounced : '');
  // Валидация — по УЖЕ введённому значению (после blur/выбора), не по каждому нажатию.
  const digits = (value || '').replace(/\D/g, '');
  const { data: validation } = useHSCodeValidation(open ? '' : digits);

  useEffect(() => setHighlighted(0), [candidates]);

  const rows = candidates ?? [];
  const showList = open && rows.length > 0;

  const pick = (code: string) => {
    onChange(code);
    setQuery('');
    setOpen(false);
    inputRef.current?.focus();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showList) return;
    // Пока список открыт, стрелки/Enter/Escape принадлежат ему — grid-навигация их не видит
    // (та же договорённость, что у ProductNameCell).
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      event.stopPropagation();
      setHighlighted((current) => Math.min(current + 1, rows.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      event.stopPropagation();
      setHighlighted((current) => Math.max(current - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      event.stopPropagation();
      pick(rows[highlighted].code);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    }
  };

  // Мягкий статус: warning ТОЛЬКО когда код введён и справочник его не подтверждает.
  const warning =
    digits && validation && (!validation.known || !validation.active)
      ? validation.known
        ? t('hsField.retired')
        : t('hsField.unknown')
      : null;
  const confirmedName = digits && validation?.known && validation.active ? validation.name : '';

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <Popover open={showList} onOpenChange={setOpen}>
        <PopoverAnchor asChild>
          <div className="relative">
            <Input
              ref={inputRef}
              type="text"
              role="combobox"
              aria-expanded={showList}
              aria-controls={listId}
              autoComplete="off"
              placeholder={placeholder ?? t('hsField.placeholder')}
              className={cn('font-mono', dense ? 'h-8 w-44 text-xs' : 'w-full', warning && 'border-warning')}
              value={value}
              onChange={(event) => {
                onChange(event.target.value);
                setQuery(event.target.value);
                setOpen(true);
              }}
              onBlur={() => setOpen(false)}
              onKeyDown={handleKeyDown}
              {...rest}
            />
            {warning ? (
              <AlertTriangle
                className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-warning"
                aria-hidden="true"
              />
            ) : confirmedName ? (
              <CheckCircle2
                className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-success"
                aria-hidden="true"
              />
            ) : null}
          </div>
        </PopoverAnchor>
        <PopoverContent
          id={listId}
          align="start"
          sideOffset={4}
          onOpenAutoFocus={(event) => event.preventDefault()}
          className="max-h-72 w-[26rem] max-w-[90vw] overflow-y-auto p-1"
        >
          {rows.map((row, index) => (
            <button
              key={row.code}
              type="button"
              // onMouseDown, не onClick: blur инпута закрыл бы список раньше клика.
              onMouseDown={(event) => {
                event.preventDefault();
                pick(row.code);
              }}
              onMouseEnter={() => setHighlighted(index)}
              className={cn(
                'flex w-full flex-col items-start gap-0.5 rounded-sm px-2 py-1.5 text-left',
                index === highlighted && 'bg-accent',
              )}
            >
              <span className="font-mono text-xs font-semibold">{formatHSCode(row.code)}</span>
              <span className="line-clamp-2 text-xs text-muted-foreground">{leafName(row.name)}</span>
            </button>
          ))}
        </PopoverContent>
      </Popover>
      {warning ? (
        <span className="text-xs text-warning">{warning}</span>
      ) : confirmedName ? (
        <span className="line-clamp-1 text-xs text-muted-foreground">{leafName(confirmedName)}</span>
      ) : null}
    </div>
  );
}

/** «8482100000» → «8482 10 000 0» — так коды печатает сама номенклатура. */

