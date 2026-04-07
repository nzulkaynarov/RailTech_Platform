# Design System Check

Проверь соответствие кода дизайн-системе проекта. Найди и исправь все нарушения.

## Аргумент

$ARGUMENTS — (опционально) путь к файлу или директории. По умолчанию — только изменённые файлы (`git diff --name-only`)

## Инструкции

### 1. Определи скоуп проверки

Если аргумент пуст:
```bash
git diff --name-only HEAD
```
Если аргумент указан — проверяй только указанные файлы.

### 2. Поиск нарушений

Для каждого `.tsx` файла в скоупе ищи:

#### Запрещённые цвета (grep в файле)
- `text-industrial-`, `bg-industrial-`, `border-industrial-` → замени на семантические токены
- `text-slate-`, `bg-slate-`, `border-slate-` → замени на `text-foreground`, `bg-background`, `border-border`
- `text-gray-`, `bg-gray-`, `border-gray-` → аналогично
- `text-emerald-`, `bg-emerald-`, `border-emerald-` → `text-success`, `bg-success/10`, `border-success/20`
- `text-amber-`, `bg-amber-`, `border-amber-` → `text-warning`, `bg-warning/10`, `border-warning/20`
- `text-red-`, `bg-red-` (кроме `text-destructive`) → `text-destructive`, `bg-destructive`
- `text-yellow-`, `bg-yellow-` → `text-warning`, `bg-warning`
- `text-white` → `text-foreground` или `text-primary-foreground` (внутри primary bg)
- `#[0-9a-fA-F]{6}` (hex цвета) → замени на `var(--color-chart-N)` или семантический токен

#### Запрещённые размеры
- `text-[` (arbitrary text size, e.g. `text-[9px]`, `text-[8px]`, `text-[11px]`) → замени на `text-xs` (минимально допустимый размер)
- `w-[` в SelectTrigger → замени на `w-32`, `w-40`, `w-48`

#### Запрещённые паттерны
- `<input` без `import { Input }` → используй shadcn `<Input>`
- `<textarea` без `import { Textarea }` → используй shadcn `<Textarea>`
- `<table` без `import { Table }` → используй shadcn `<Table>` + `<TableHeader>` + `<TableBody>` + `<TableRow>` + `<TableHead>` + `<TableCell>`
- `<aside` для sidebar → используй shadcn `<Sidebar>` + `<SidebarProvider>`
- `alert(` → используй `toast()` из sonner / `toast.error()` / `toast.success()`
- `dangerouslySetInnerHTML` → используй `<Trans>` из react-i18next
- `style={{ backgroundColor` → используй `bg-[var(--color-chart-N)]` Tailwind классы
- `style={{` (inline styles для статичных значений) → используй Tailwind классы
- Emoji символы (🟢, ⚪, 🎯, etc.) → используй lucide-react иконки

#### Отсутствие i18n
- Строки на русском/английском в JSX без `t()` (кроме имён собственных и форматов)
- Zod validation messages без `t()` → используй factory pattern `createSchema(t)`
- Hardcoded label arrays (например `DOC_TYPES`) → используй `labelKey` + `t(item.labelKey)`

### 3. Автоматическое исправление

Для каждого нарушения:
1. Прочитай файл
2. Выполни замену через Edit tool
3. Убедись что `npm run build` проходит

### 4. Вывод отчёта

```
## Design System Check Report

### Нарушений найдено: N
### Исправлено: M

| Файл | Тип нарушения | Строка | Было → Стало |
|------|---------------|--------|--------------|
| ... | Запрещённый цвет | 42 | `bg-slate-100` → `bg-muted` |

### Сборка: ✅ OK / ❌ Failed
```
