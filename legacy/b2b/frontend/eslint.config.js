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
  { ignores: ['dist'] },
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
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      // RailTech CLAUDE.md enforcement
      'railtech/no-hardcoded-colors': 'error',
      'railtech/no-arbitrary-text-size': 'error',
    },
  },
)
