import { defineConfig } from "orval";

// Клиент API генерируется из OpenAPI бэкенда (SPEC §10.3): `pnpm api:generate`.
// Ручные типы API запрещены (CLAUDE.md §4).
export default defineConfig({
  crm: {
    input: "../docs/api/openapi.json",
    output: {
      mode: "split",
      target: "src/api/generated/crm.ts",
      schemas: "src/api/generated/model",
      client: "fetch",
      clean: true,
      override: {
        mutator: { path: "src/api/http.ts", name: "http" },
      },
    },
  },
});
