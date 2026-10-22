import { defineConfig } from "orval";

// Клиент API генерируется из OpenAPI бэкенда (SPEC §10.3): `pnpm api:generate`.
// Ручные типы API запрещены (CONVENTIONS.md §4). ADR-0021: хуки TanStack Query + fetch-функции
// (те же имена) поверх общего мутатора `http`; функции возвращают тело ответа, не конверт.
export default defineConfig({
  crm: {
    input: "../docs/api/openapi.json",
    output: {
      mode: "split",
      target: "src/api/generated/crm.ts",
      schemas: "src/api/generated/model",
      client: "react-query",
      httpClient: "fetch",
      clean: true,
      override: {
        mutator: { path: "src/api/http.ts", name: "http" },
        fetch: { includeHttpResponseReturnType: false },
        query: { shouldExportKeys: true },
      },
    },
  },
});
