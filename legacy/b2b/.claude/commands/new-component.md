# New Component

Создай новый React компонент по конвенциям проекта.

## Аргумент

$ARGUMENTS — имя компонента и опционально директория. Примеры:
- `StatusTimeline` — создаст в `src/components/ui/`
- `Catalog/ProductFilters` — создаст в `src/components/Catalog/`
- `Dashboard/RevenueChart` — создаст в `src/components/Dashboard/`

## Инструкции

1. Определи путь файла:
   - Если указана директория: `src/components/<Dir>/<Name>.tsx`
   - Если без директории: `src/components/ui/<Name>.tsx`
   - Если имя содержит `/subcomponents/`: создай в subcomponents

2. Создай компонент используя **шаблон проекта**:

```tsx
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
// ... другие импорты

interface <Name>Props {
  className?: string;
  // ... props
}

export function <Name>({ className, ...props }: <Name>Props) {
  const { t } = useTranslation();
  return (
    <div className={cn('', className)}>
      {/* content */}
    </div>
  );
}
```

## Конвенции

- **Именование:** PascalCase для файлов и компонентов
- **Экспорт:** Named export (не default)
- **Стили:** Tailwind CSS + `cn()` для условных классов
- **UI примитивы:** Используй shadcn/ui компоненты из `@/components/ui/`
- **Иконки:** `lucide-react`
- **i18n:** `useTranslation()` + `t('key')` для ВСЕХ UI текстов (без хардкода)
- **Типы:** TypeScript интерфейсы для props (не type aliases)

## Дизайн-система (ОБЯЗАТЕЛЬНО)

**Цвета — ТОЛЬКО семантические токены:**
- `text-foreground`, `text-muted-foreground` — НЕ `text-slate-*`, `text-gray-*`
- `bg-background`, `bg-card`, `bg-muted` — НЕ `bg-white`, `bg-slate-*`
- `border-border` — НЕ `border-slate-200`
- `bg-primary`, `text-primary` — НЕ `bg-blue-600`, `text-blue-600`
- `text-destructive` — НЕ `text-red-600`

**Графики (recharts):**
- `fill="var(--color-chart-1)"` — НЕ `fill="#4f46e5"`
- `stroke="var(--color-border)"` — НЕ `stroke="#e5e7eb"`

**Размеры текста — ТОЛЬКО стандартная шкала:**
- `text-xs`, `text-sm`, `text-base` — НЕ `text-[10px]`, `text-[11px]`

**Запрещено:**
- `text-industrial-*`, `bg-industrial-*` — не существует в теме
- Inline `style={{ color: ... }}` — используй Tailwind классы
- Emoji в коде — используй `lucide-react` иконки
- Raw `<input>`, `<textarea>` — используй `<Input>`, `<Textarea>` из shadcn

## После создания

- Проверь: `npm run build` (НЕ lint:tsc — build строже)
- Сообщи путь к созданному файлу
