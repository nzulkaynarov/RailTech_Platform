# New Store

Создай новый Zustand store для управления состоянием.

## Аргумент

$ARGUMENTS — имя стора (например: `notification`, `filter`, `workflow`)

## Инструкции

Создай файл: `src/store/<name>Store.ts`

```tsx
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface <Name>State {
  // Данные
  // ...

  // Действия
  // ...
  reset: () => void;
}

const initialState = {
  // начальные значения
};

export const use<Name>Store = create<<Name>State>()(
  persist(
    (set, get) => ({
      ...initialState,

      // Действия
      reset: () => set(initialState),
    }),
    {
      name: 'railtech-<name>',
      partialize: (state) => ({
        // Указать только те поля, которые нужно сохранять в localStorage
      }),
    }
  )
);
```

### Если persist не нужен (runtime-only state):

```tsx
import { create } from 'zustand';

interface <Name>State {
  // ...
  reset: () => void;
}

export const use<Name>Store = create<<Name>State>()((set, get) => ({
  // начальные значения и действия
  reset: () => set({ /* initial values */ }),
}));
```

## Конвенции

- Файл: `src/store/<name>Store.ts` (camelCase + Store суффикс)
- Хук экспорт: `use<Name>Store` (PascalCase)
- persist key: `railtech-<name>` (kebab-case с railtech- префиксом)
- `partialize` — только необходимые для persist поля
- `reset()` метод для очистки state
- Не использовать React Context — только Zustand

## После создания

```bash
npm run lint:tsc
```
