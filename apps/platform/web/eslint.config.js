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

const QUERY_KEY_RULES = [
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
];

// Системных полей браузера в экранах нет (UX-2a, platform-frontend.md §5): дата `mm/dd/yyyy`, «Choose Files» и родной
// `select` выбиваются из русского интерфейса. Исключение — сами `shared/ui/DateField` и `shared/ui/FileField`.
const NATIVE_FIELD_TYPES = "/^(date|datetime-local|file)$/";
const NATIVE_FIELD_RULES = [
  {
    selector: 'JSXOpeningElement[name.name="select"]',
    message:
      "Родной <select> запрещён: antd Select с подписью label for (поиск — если вариантов больше 7).",
  },
  {
    selector: `JSXOpeningElement[name.name=/^(input|Input)$/] > JSXAttribute[name.name="type"][value.value=${NATIVE_FIELD_TYPES}]`,
    message:
      "Системное поле даты или файла запрещено: DateField / DateRangeField (shared/ui/DateField) или FileField / FilePicker (shared/ui/FileField).",
  },
];

// Деньги и статусы — одно правило в `shared` (UX-2b, platform-frontend.md §5). Модуль не подменяет `UZS` на «сум» и не пишет
// код валюты в подпись: это делают `formatMoney`/`MoneyText`/`currencyLabel`; код валюты компании в данных — `HOME_CURRENCY`.
// Цвет статуса модуль не выбирает: `<StatusTag kind status>` берёт его из единственной карты `STATUS_TONE`; `tone` — только
// литерал для флагов без статуса (срочно, просрочено, только чтение).
const MONEY_STATUS_RULES = [
  {
    selector: "Literal[value=/^UZS$/i]",
    message:
      'Литерал "UZS" в модуле запрещён: подпись «сум» делает formatMoney / MoneyText / currencyLabel (shared/lib/money), код валюты компании — HOME_CURRENCY.',
  },
  {
    selector: "TemplateElement[value.raw=/\\bUZS\\b/i], JSXText[value=/\\bUZS\\b/i]",
    message:
      "«UZS» в подписи запрещён: валюту подписывает formatMoney / MoneyText / currencyLabel.",
  },
  {
    selector:
      "ImportDeclaration[source.value=/shared\\/lib\\/statuses$/] > ImportSpecifier[imported.name=/^(StatusTone|TONE_STYLE|STATUS_TONES|MEANING_TONE)$/]",
    message:
      "Локальная карта цветов статусов запрещена: вид и код в STATUS_TONE (shared/lib/statuses), тег — <StatusTag kind status>, значок — statusStyle().",
  },
  {
    selector: 'JSXAttribute[name.name="tone"] > JSXExpressionContainer',
    message:
      "Вычисляемый цвет статуса запрещён: <StatusTag kind status> (карта STATUS_TONE в shared/lib/statuses); tone — только литерал для флага без статуса.",
  },
  {
    selector: 'JSXOpeningElement[name.name="Tag"] > JSXAttribute[name.name="color"]',
    message: "Цветной antd Tag в модуле запрещён: StatusTag (shared/ui) — цвет из STATUS_TONE.",
  },
];

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
      "no-restricted-syntax": ["error", ...QUERY_KEY_RULES],
    },
  },
  {
    files: ["src/shared/**/*.tsx", "src/app/**/*.tsx", "src/dev/**/*.tsx"],
    ignores: ["src/shared/ui/DateField.tsx", "src/shared/ui/FileField.tsx"],
    rules: {
      "no-restricted-syntax": ["error", ...QUERY_KEY_RULES, ...NATIVE_FIELD_RULES],
    },
  },
  {
    files: [
      "src/modules/**/*.{ts,tsx}",
      "src/features/**/*.{ts,tsx}",
      "src/entities/**/*.{ts,tsx}",
    ],
    ignores: ["**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        ...QUERY_KEY_RULES,
        ...NATIVE_FIELD_RULES,
        ...MONEY_STATUS_RULES,
      ],
    },
  },
  {
    files: ["src/modules/**/*.test.tsx", "src/features/**/*.test.tsx"],
    rules: {
      "no-restricted-syntax": ["error", ...QUERY_KEY_RULES, ...NATIVE_FIELD_RULES],
    },
  },
  {
    files: ["**/*.js"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
);
