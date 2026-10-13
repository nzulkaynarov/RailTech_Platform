# Code Review

Проведи ревью кода текущих изменений или указанного PR.

## Аргумент

$ARGUMENTS — номер PR или пусто для ревью текущих изменений

## Инструкции

### Если указан номер PR:
```bash
gh pr diff $ARGUMENTS
gh pr view $ARGUMENTS
```

### Если без аргументов — ревью текущего diff:
```bash
git diff HEAD
git diff --staged
```

## Чек-лист ревью

Для каждого изменённого файла проверь:

### 1. Корректность
- Логические ошибки, off-by-one, null/undefined
- Race conditions в async коде
- Утечки памяти (подписки, таймеры без cleanup)

### 2. Безопасность
- XSS через `dangerouslySetInnerHTML` или неэкранированный ввод
- Утечка секретов (токены, ключи в коде)

### 3. Производительность
- Ненужные ре-рендеры (отсутствующие memo, useMemo, useCallback)
- Тяжёлые вычисления в рендер-цикле

### 4. Дизайн-система (ОБЯЗАТЕЛЬНАЯ проверка)
- **Запрещённые цвета:** `text-industrial-*`, `bg-industrial-*`, `text-slate-*`, `bg-slate-*`, hex-цвета
- **Запрещённые размеры:** `text-[Npx]` — только стандартная шкала Tailwind
- **Запрещённые паттерны:** raw `<input>`, emoji, `dangerouslySetInnerHTML`, inline styles
- **Обязательные:** shadcn/ui компоненты, семантические токены, `t()` для текстов

### 5. Конвенции проекта
- Импорты через `@/` alias
- shadcn/ui + `cn()` для стилей
- Zustand для стейта (не Context)
- React Query для серверного стейта
- i18next для текстов UI

### 6. UX/Доступность
- `aria-label` на всех icon-only кнопках
- Keyboard navigation (focusable, tabindex)
- Loading/error states
- Мобильная адаптивность

### 7. Сборка
```bash
npm run build
```
Если не собирается — **Block**.

## Формат вывода

Для каждой проблемы:
```
🔴 КРИТИЧНО / 🟡 ВАЖНО / 🔵 ЗАМЕТКА

**Файл:** `path/to/file.tsx:42`
**Проблема:** Описание
**Решение:** Как исправить
```

В конце — общая оценка: ✅ Approve / ⚠️ Request changes / ❌ Block
