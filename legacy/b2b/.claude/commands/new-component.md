# New Component

Создай новый React-компонент по конвенциям проекта.

## Аргумент

$ARGUMENTS — имя и опционально директория: `Catalog/ProductFilters`, `CRM/DealTimeline`.

## Куда класть

- **Доменная папка**: `src/components/<Домен>/<Name>.tsx` (Admin, CRM, Billing, Settings, Sourcing, Dashboard, Shared…). Посмотри соседей: `ls src/components/`.
- **`src/components/ui/` — ТОЛЬКО shadcn-примитивы.** Свои компоненты туда НЕ кладём.
- Перед созданием проверь, нет ли уже похожего компонента в домене — расширить лучше, чем дублировать.

## Главный принцип: повторяй за свежим соседом

```bash
git log --oneline --diff-filter=A -10 -- frontend/src/components/<Домен>/
```

Прочитай свежий компонент домена: структура props, работа с хуками/React Query, паттерн диалогов/форм — повтори.

## Каркас

```tsx
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

interface <Name>Props {
  className?: string;
}

export function <Name>({ className }: <Name>Props) {
  const { t } = useTranslation();
  return <div className={cn('', className)}>{/* ... */}</div>;
}
```

## Инварианты

- Named export, PascalCase, интерфейс для props.
- **Только shadcn/ui** (`<Input>`, `<Textarea>`, `<Table>`, `<Dialog>`…) — не raw-элементы.
- **Только семантические токены**: `text-foreground`, `bg-muted`, `text-destructive`, `bg-success/10`… — НЕ `text-slate-*`, `text-white`, hex. Графики: `var(--color-chart-N)`.
- **Размеры текста** — только шкала Tailwind, минимум `text-xs`. Никаких `text-[10px]`.
- Никаких inline-`style` для статики, emoji (иконки — lucide-react), `alert()` (только `toast()` из sonner).
- Все тексты через `t()`, ключи в ОБОИХ `ru.json` и `en.json`; zod-сообщения — factory `createSchema(t)`.
- Формы — по паттерну соседних диалогов (react-hook-form + zod, если сосед так делает).

## Проверка

```bash
cd frontend && npm run build   # НЕ lint:tsc — build строже
```

Затем `/design-check` по файлу. Если компонент виден пользователю в ключевом флоу — прогнать `/ux-review`.
