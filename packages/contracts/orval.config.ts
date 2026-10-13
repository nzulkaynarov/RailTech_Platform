import { defineConfig } from "orval";

// Клиент Integration API для CRM (M3-CRM-02/03): fetch-функции без фреймворка, типы — рядом.
// CRM-бэкенд на Python зовёт ERP через httpx по тому же OpenAPI (клиент генерируется в apps/crm на M3).
export default defineConfig({
  erpIntegration: {
    input: "openapi/erp-integration.yaml",
    output: {
      mode: "split",
      target: "generated/crm/erp-integration.ts",
      schemas: "generated/crm/model",
      client: "fetch",
      clean: true,
      prettier: false,
      override: {
        fetch: { includeHttpResponseReturnType: false },
      },
    },
  },
});
