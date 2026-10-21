import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

// Ключи кэша — только сгенерированные orval (`get…QueryKey`), как в CRM (ADR-0021): ручной массив
// молча не совпадёт с ключом хука.
const QUERY_KEY_METHODS = [
  "invalidateQueries",
  "refetchQueries",
  "cancelQueries",
  "removeQueries",
  "resetQueries",
  "setQueriesData",
  "getQueriesData",
  "fetchQuery",
  "prefetchQuery",
  "ensureQueryData",
  "query",
].join("|");
const LITERAL_KEY_MESSAGE = "Ключ кэша — сгенерированный orval (get…QueryKey), не массив-литерал.";

export default tseslint.config(
  {
    ignores: ["dist", "coverage", "playwright-report", "test-results", "src/shared/api/generated"],
  },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "no-restricted-syntax": [
        "error",
        {
          selector: `CallExpression[callee.property.name=/^(${QUERY_KEY_METHODS})$/] > ObjectExpression > Property[key.name="queryKey"] > ArrayExpression.value`,
          message: LITERAL_KEY_MESSAGE,
        },
        {
          selector: `CallExpression[callee.name=/^(useQuery|useSuspenseQuery|useInfiniteQuery)$/] > ObjectExpression > Property[key.name="queryKey"] > ArrayExpression.value`,
          message: LITERAL_KEY_MESSAGE,
        },
        {
          selector: `CallExpression[callee.property.name=/^(setQueryData|getQueryData|getQueryState)$/][arguments.0.type="ArrayExpression"]`,
          message: LITERAL_KEY_MESSAGE,
        },
      ],
    },
  },
  {
    files: ["**/*.js"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
);
