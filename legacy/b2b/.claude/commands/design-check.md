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
- `#[0-9a-fA-F]{6}` (hex цвета) → замени на `var(--color-chart-N)` или семантический токен

#### Запрещённые размеры
- `text-[` (arbitrary text size) → замени на `text-xs`, `text-sm` и т.д.
- `w-[` в SelectTrigger → замени на `w-32`, `w-40`, `w-48`

#### Запрещённые паттерны
- `<input` без `import { Input }` → используй shadcn `<Input>`
- `<textarea` без `import { Textarea }` → используй shadcn `<Textarea>`
- `dangerouslySetInnerHTML` → используй `<Trans>` из react-i18next
- `style={{` (inline styles) → используй Tailwind классы
- Emoji символы (🟢, ⚪, 🎯, etc.) → используй lucide-react иконки

#### Отсутствие i18n
- Строки на русском/английском в JSX без `t()` (кроме имён собственных и форматов)

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
