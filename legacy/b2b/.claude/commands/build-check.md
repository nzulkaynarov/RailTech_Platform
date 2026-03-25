# Build Check

Полная проверка сборки проекта. Это **финальный гейткипер** — ни один коммит не должен проходить если build не зелёный.

## Инструкции

1. **Полная сборка (TypeScript + Vite):**
   ```bash
   npm run build
   ```
   ВАЖНО: используй именно `npm run build` (= `tsc -b && vite build`), а НЕ `npm run lint:tsc`.
   `tsc -b` строже: unused imports/variables = ошибки, не предупреждения.

2. Если есть ошибки TypeScript:
   - **TS6133 (unused import):** Удали импорт. НЕ используй `_` prefix.
   - **TS6198 (unused destructured):** Удали неиспользуемый элемент из деструктуризации.
   - **TS2345/TS2367 (type mismatch):** Прочитай оба типа, найди расхождение, исправь.
   - После исправлений — снова `npm run build`.

3. **Проверка дизайн-системы** (быстрый grep):
   ```bash
   grep -r 'text-\[10px\]\|bg-industrial\|text-industrial\|border-industrial' src/ --include='*.tsx' -l
   grep -r '#[0-9a-fA-F]\{6\}' src/ --include='*.tsx' -l
   ```
   Если найдены нарушения — исправь и пересобери.

4. **Проверка импортов:** Убедись что нет:
   - Битых `@/` путей
   - Неиспользуемых импортов (tsc -b их поймает)

5. **Размер бандла:** После успешной сборки:
   ```bash
   du -sh dist/
   ls -la dist/assets/ | head -20
   ```

6. **Итог:**
   - ✅ TypeScript: OK / ❌ X ошибок
   - ✅ Build: OK / ❌ Failed
   - ✅ Design system: OK / ❌ X нарушений
   - 📦 Bundle size: XX MB
