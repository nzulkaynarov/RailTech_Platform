# New Page

Создай новую страницу и подключи её к навигации.

## Аргумент

$ARGUMENTS — имя страницы (например: `SupplierRating`, `BudgetControl`, `ContractManagement`)

## Инструкции

### 1. Создай файл страницы

Путь: `src/pages/<Name>Page.tsx`

```tsx
import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
// Иконка из lucide-react соответствующая содержанию

interface <Name>PageProps {
  onNavigate?: (target: string) => void;
}

export function <Name>Page({ onNavigate }: <Name>PageProps) {
  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Заголовок</h1>
          <p className="text-sm text-muted-foreground">Описание страницы</p>
        </div>
      </div>

      {/* Content */}
      <Card>
        <CardContent className="p-6">
          {/* Содержимое */}
        </CardContent>
      </Card>
    </div>
  );
}
```

### 2. Добавь в App.tsx

- Добавь тип в `Page` union: `| { type: '<page-id>' }`
- Добавь `'<page-id>'` в `validTypes` массив в `handleNavigate`
- Добавь `case` в `switch` блок
- Добавь breadcrumb в `getBreadcrumbs`

### 3. Добавь в навигацию AppShell

- Определи к какому статусу относится (BUYER / SELLER / MANUFACTURER)
- Добавь `NavItem` в соответствующую функцию `get*Navigation()` в `src/layouts/AppShell.tsx`

### 4. Проверь

```bash
npm run lint:tsc
```

## Конвенции

- Файл: PascalCase + `Page` суффикс
- Named export (не default)
- Page ID в kebab-case (`supplier-rating`, `budget-control`)
- Для SELLER и MANUFACTURER страниц — не забудь `onNavigate` prop
