import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';

/**
 * Правила RailTech из CLAUDE.md §5 (те же, что в apps/erp/frontend): только семантические токены
 * shadcn (`bg-primary`, `text-destructive`…) и шкала размеров Tailwind — без палитры и пикселей.
 */
const railtechPlugin = {
  rules: {
    'no-hardcoded-colors': {
      meta: {
        type: 'problem',
        messages: {
          found:
            'Use semantic tokens (bg-primary, text-destructive, etc.) instead of hardcoded color "{{match}}". See CLAUDE.md §5.',
        },
      },
      create(context) {
        const FORBIDDEN =
          /\b(text|bg|border|ring|outline|fill|stroke)-(red|green|blue|yellow|orange|pink|purple|violet|indigo|cyan|teal|lime|emerald|amber|rose|fuchsia|sky|slate|gray|zinc|neutral|stone|warm)-\d+/;
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
    'no-arbitrary-text-size': {
      meta: {
        type: 'problem',
        messages: {
          found: 'Use Tailwind scale (text-xs, text-sm, etc.) instead of arbitrary "{{match}}". See CLAUDE.md §5.',
        },
      },
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
  { ignores: ['dist', 'public', 'src/api/portal.d.ts', 'src/api/crm-form.d.ts'] },
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
      railtech: railtechPlugin,
    },
    rules: {
      // Правила React Compiler включены целиком (CLAUDE.md §5) — в новом коде долга нет.
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      'railtech/no-hardcoded-colors': 'error',
      'railtech/no-arbitrary-text-size': 'error',
    },
  },
  {
    // Vendored-примитивы shadcn/ui экспортируют варианты рядом с компонентом — контракт реестра.
    files: ['src/components/ui/*.tsx'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
);
