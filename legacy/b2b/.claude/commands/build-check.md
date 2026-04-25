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

6. **Проверка N+1 и aggregate паттернов:**
   ```bash
   echo "--- Individual .count() calls in views (should be minimal) ---"
   grep -rn '\.count()' backend/*/views/ --include='*.py' | wc -l
   echo "--- aggregate() usage (should be present in dashboard/stats views) ---"
   grep -rn 'aggregate(' backend/ --include='*.py' | wc -l
   ```
   Если в views много `.count()` — рекомендуй рефакторинг на `aggregate()`.

7. **Итог:**
   - ✅ TypeScript: OK / ❌ X ошибок
   - ✅ Build: OK / ❌ Failed
   - ✅ Design system: OK / ❌ X нарушений
   - ✅ N+1 queries: OK / ⚠️ X подозрительных .count()
   - 📦 Bundle size: XX MB
