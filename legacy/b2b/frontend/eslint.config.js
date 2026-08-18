import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

/**
 * Custom RailTech ESLint rules enforcing CLAUDE.md coding standards.
 * These catch violations that were previously only found by manual AI review.
 */
const railtechPlugin = {
  rules: {
    // Rule 4: No hardcoded non-semantic Tailwind colors
    'no-hardcoded-colors': {
      meta: { type: 'problem', messages: { found: 'Use semantic tokens (bg-primary, text-destructive, etc.) instead of hardcoded color "{{match}}". See CLAUDE.md Rule 4.' } },
      create(context) {
        const FORBIDDEN = /\b(text|bg|border|ring|outline|fill|stroke)-(red|green|blue|yellow|orange|pink|purple|violet|indigo|cyan|teal|lime|emerald|amber|rose|fuchsia|sky|slate|gray|zinc|neutral|stone|warm)-\d+/;
        const TEXT_WHITE_BLACK = /\b(text-white|text-black)\b/;
        return {
          Literal(node) {
            if (typeof node.value !== 'string') return;
            const m = node.value.match(FORBIDDEN) || node.value.match(TEXT_WHITE_BLACK);
            if (m) context.report({ node, messageId: 'found', data: { match: m[0] } });
          },
          TemplateLiteral(node) {
            for (const q of node.quasis) {
              const m = q.value.raw.match(FORBIDDEN) || q.value.raw.match(TEXT_WHITE_BLACK);
              if (m) context.report({ node: q, messageId: 'found', data: { match: m[0] } });
            }
          },
        };
      },
    },
    // Rule 4: No arbitrary pixel text sizes
    'no-arbitrary-text-size': {
      meta: { type: 'problem', messages: { found: 'Use Tailwind scale (text-xs, text-sm, etc.) instead of arbitrary "{{match}}". See CLAUDE.md Rule 4.' } },
      create(context) {
        const FORBIDDEN = /\btext-\[\d+px\]/;
        return {
          Literal(node) {
            if (typeof node.value !== 'string') return;
            const m = node.value.match(FORBIDDEN);
            if (m) context.report({ node, messageId: 'found', data: { match: m[0] } });
          },
          TemplateLiteral(node) {
            for (const q of node.quasis) {
              const m = q.value.raw.match(FORBIDDEN);
              if (m) context.report({ node: q, messageId: 'found', data: { match: m[0] } });
            }
          },
        };
      },
    },
  },
};

export default tseslint.config(
  // e2e/ holds Playwright browser specs that depend on @playwright/test (a
  // separate, optional dev install). Keep them out of the app lint run.
  { ignores: ['dist', 'e2e', 'playwright.config.ts'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'railtech': railtechPlugin,
    },
    rules: {
      // eslint 10 + eslint-plugin-react-hooks 7 (17-08): `configs.recommended` в v7 включает
      // правила React Compiler (set-state-in-effect, refs-during-render, purity …) — 77 новых
      // ошибок по живому коду. Это отдельная волна рефакторинга, а не побочный эффект бампа
      // линтера, поэтому здесь ЯВНО только классические правила хуков — поведение как у v5.
      // eslint-plugin-react-hooks 7 приносит правила React Compiler. Включаем ВЕСЬ
      // recommended и точечно гасим то, что осталось долгом (18-08): так починенное
      // закрепляется гейтом, а не откатывается следующей правкой.
      ...reactHooks.configs.recommended.rules,
      // ── Долг, разобранный 2026-08-18 (`Docs/dev/specs/plan-remaining-work-2026-08-17.md` §2.3)
      // 47 мест: setState в эффекте. Разобраны по категориям; настоящие каскады починены,
      // остальное — «синхронизация с props» (канон: derived / adjust-in-render) и легальные
      // эффекты (подписки, таймеры, async). Включать после переписывания категории B.
      'react-hooks/set-state-in-effect': 'off',
      // 10 мест, все в билдере КП: паттерн «live mirror ref» (`ref.current = value` в рендере),
      // чтобы колбэки видели свежие данные без пересоздания. Сегодня не баг (значения
      // иммутабельны и перезаписываются целиком), но в concurrent-рендере ref может пережить
      // выброшенный рендер. Лечится объединением состояний draft-машины в одно — это
      // рефакторинг сердца билдера, отдельной волной с прогоном глазами.
      'react-hooks/refs': 'off',
      // 3 места: `window.location.hash = ...` — hash-навигация вместо React Router (ADR-0005).
      // Компилятор видит мутацию внешнего значения; архитектурное решение, а не дефект.
      'react-hooks/immutability': 'off',
      // 2 места (GridRow, SectionNoteRow): ручная мемоизация ref-колбэка, которую компилятор
      // не может сохранить. Стабильность ссылки там ОБЯЗАТЕЛЬНА (иначе виртуализатор
      // переобсервит строку и список прыгает — B3). Потеря авто-оптимизации, не баг.
      'react-hooks/preserve-manual-memoization': 'off',
      // 1 место: `useStaticMemo(factory, deps)` — осознанная обёртка с динамическим списком.
      'react-hooks/use-memo': 'off',
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      // RailTech CLAUDE.md enforcement
      'railtech/no-hardcoded-colors': 'error',
      'railtech/no-arbitrary-text-size': 'error',
    },
  },
  {
    // Vendored-примитивы shadcn/ui: апстрим экспортирует варианты (`buttonVariants`,
    // `badgeVariants`, `useFormField`, `useSidebar`) РЯДОМ с компонентом — это контракт
    // реестра, компонент возвращается одной командой `npx shadcn add <name>` и любая наша
    // перестановка при этом затрётся. Правило Fast Refresh здесь только шумит.
    files: ['src/components/ui/badge.tsx', 'src/components/ui/button.tsx', 'src/components/ui/form.tsx', 'src/components/ui/sidebar.tsx', 'src/components/ui/tabs.tsx', 'src/components/ui/toggle.tsx'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
  {
    // Тонкие ре-экспорт-шимы: файл существует РОВНО чтобы старые пути импорта продолжали
    // работать после распила страницы на пакет. Компонентов он не определяет — Fast Refresh
    // здесь нечего обновлять.
    files: ['src/pages/AdminCatalogPage.tsx', 'src/pages/AdminKYCPage.tsx', 'src/pages/AdminUsersPage.tsx', 'src/pages/RequestDetailPage.tsx'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
)
