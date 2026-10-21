import {
  getGetHealthMockHandler,
  getRailTechPlatformBFFAPICRMERPMock,
} from "../shared/api/generated/platform-bff.msw";

/**
 * Моки API Платформы для `pnpm dev:mock`, e2e и тестов. Общий набор генерирует orval из контракта
 * (случайные данные faker); здесь поверх — детерминированные ответы, чтобы скриншоты и e2e не плавали.
 */
export const handlers = [
  getGetHealthMockHandler({
    status: "ok",
    checks: { redis: "ok", crm: "ok", erp: "ok" },
    version: "0.1.0",
  }),
  ...getRailTechPlatformBFFAPICRMERPMock(),
];
