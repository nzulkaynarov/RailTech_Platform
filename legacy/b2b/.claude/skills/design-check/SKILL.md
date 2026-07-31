---
name: design-check
description: "Проверка соответствия дизайн-системе проекта (семантические токены, shadcn/ui, шкала размеров, i18n) с автоисправлением. Использовать после правок .tsx, перед коммитом UI-изменений, или по запросу «проверь дизайн-систему». Поиск нарушений — скриптом, исправление — вручную."
---

# /design-check — соответствие дизайн-системе

## Шаг 1. Скрипт находит нарушения (0 токенов на поиск)

```bash
bash .claude/skills/design-check/scripts/check.sh              # изменённые .tsx
bash .claude/skills/design-check/scripts/check.sh --all        # весь frontend/src
bash .claude/skills/design-check/scripts/check.sh <файл|папка> # явный скоуп
```

## Шаг 2. Исправить каждую находку

Таблица замен:

| Найдено | Замена |
|---|---|
| `text-slate-*`, `text-gray-*` | `text-foreground` / `text-muted-foreground` |
| `bg-slate-*`, `bg-gray-*`, `bg-white` | `bg-background` / `bg-card` / `bg-muted` |
| `border-slate-*` | `border-border` |
| `*-emerald-*`, `*-green-*` | `text-success`, `bg-success/10`, `border-success/20` |
| `*-amber-*`, `*-yellow-*` | `text-warning`, `bg-warning/10`, `border-warning/20` |
| `*-red-*` | `text-destructive`, `bg-destructive` |
| `*-blue-*`, `*-sky-*` | `text-info` / `text-primary` (по смыслу) |
| `text-white` | `text-primary-foreground` (на цветном фоне) / `text-foreground` |
| hex `#xxxxxx` | `var(--color-chart-N)` или семантический токен |
| `text-[Npx]` | ближайший из шкалы, минимум `text-xs` |
| raw `<input>`/`<textarea>`/`<table>`/`<select>` | shadcn `<Input>`/`<Textarea>`/`<Table>`/`<Select>` |
| `<aside>` как sidebar | shadcn `<Sidebar>` + `<SidebarProvider>` |
| `alert(...)` | `toast.error(...)` / `toast.success(...)` (sonner) |
| `style={{ backgroundColor }}` | `bg-[var(--color-chart-N)]` |
| emoji | иконка lucide-react |

Допустимые исключения существуют (hex внутри генерации SVG/canvas-экспорта и т.п.) — каждое исключение назвать в отчёте явно, а не молча пропустить.

## Шаг 3. i18n (скриптом не ловится — глазами по диффу)

- Строки на русском/английском в JSX без `t()` → ключи в ОБА `ru.json` и `en.json`.
- Zod-сообщения → factory `createSchema(t)`.
- Массивы label'ов → `labelKey` + `t(item.labelKey)`.
- Для сплошной проверки симметрии ключей — `/check-i18n`.

## Шаг 4. Проверка сборки

```bash
cd frontend && npm run build   # НЕ lint:tsc — build строже (tsc -b)
```

## Шаг 5. Отчёт

```
## Design System Check

Нарушений: N · Исправлено: M · Допустимых исключений: K (перечислить)

| Файл:строка | Тип | Было → Стало |
|---|---|---|

Сборка: ✅ / ❌
```
