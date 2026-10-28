import { HttpResponse, http, passthrough } from "msw";

import {
  getGetHealthMockHandler,
  getRailTechPlatformBFFAPICRMERPMock,
} from "../shared/api/generated/platform-bff.msw";
import type { ChangePasswordIn, LoginIn, MeUpdate } from "../shared/api/generated/model";
import { aboutHandlers } from "./aboutHandlers";
import { adminAuditHandlers } from "./adminAudit";
import { adminBusHandlers } from "./adminBus";
import { adminIntegrationsHandlers } from "./adminIntegrations";
import { adminCompanyHandlers } from "./adminCompany";
import { adminRolesHandlers } from "./adminRoles";
import { botKbHandlers } from "./botKb";
import { companyArticlesHandlers } from "./companyArticlesHandlers";
import { crmLeadsHandlers } from "./crmLeads";
import { crmMessagesHandlers } from "./crmMessages";
import { edsApprovalsHandlers } from "./edsApprovals";
import { edsPaymentsHandlers } from "./edsPayments";
import { bridgeHandlers } from "./bridgeHandlers";
import { edsLettersHandlers } from "./edsLetters";
import { erpCalcHandlers } from "./erpCalc";
import { erpStockHandlers } from "./erpStock";
import { adminUsersHandlers } from "./adminUsers";
import { edsDocumentsHandlers } from "./edsDocuments";
import { eventStreamHandlers } from "./eventStream";
import { isEmployeeDisabled } from "./fixtures/employees";
import { feedHandlers } from "./feedHandlers";
import { profileHandlers } from "./profileHandlers";
import { setupHandlers } from "./setupHandlers";
import { ticketsHandlers } from "./ticketsHandlers";
import {
  DEMO_WRONG_CURRENT_PASSWORD,
  DEMO_WRONG_PASSWORD,
  findUser,
  findUserById,
  forgetTemporaryPassword,
  temporaryPasswordOf,
  updateExtraUser,
} from "./fixtures/users";
import {
  buildMe,
  buildSession,
  endSession,
  readSession,
  startSession,
  updateSession,
} from "./mockSession";

function failure(
  status: number,
  code: string,
  message: string,
  source: "bff" | "crm" | "erp" = "bff",
) {
  return HttpResponse.json({ code, message, source }, { status });
}

const sessionExpired = () => failure(401, "SESSION_EXPIRED", "Сессия истекла");

/**
 * Моки API Платформы для `pnpm dev:mock`, e2e и тестов. Общий набор генерирует orval из контракта (случайные
 * данные faker); здесь поверх — сессия, роли-данные (ADR-0012: системные и шаблоны `platform-rbac.yaml`) и
 * детерминированные счётчики, чтобы скриншоты и e2e не плавали. Вход принимает любой непустой пароль, кроме
 * `wrong-password`; адреса `disabled@`, `norole@`, `busy@`, `down@` дают ошибки входа.
 */
export const handlers = [
  // Сгенерированные orval обработчики слушают `*/queue`, `*/me`, `*/health`…: без этой «калитки» они перехватили бы и
  // переходы по страницам SPA (`/dashboard/queue`). API живёт только под `/api/v1/`, всё остальное — как есть.
  http.all("*", ({ request }) =>
    new URL(request.url).pathname.startsWith("/api/v1/") ? undefined : passthrough(),
  ),

  http.post("*/auth/login", async ({ request }) => {
    const body = (await request.json()) as LoginIn;
    const user = findUser(body.email);
    // Сотруднику выдан временный пароль: войти можно только с ним (до смены пароля).
    const temporary = user ? temporaryPasswordOf(user.email) : undefined;
    if (
      !user ||
      body.password === DEMO_WRONG_PASSWORD ||
      (temporary && body.password !== temporary)
    ) {
      return failure(401, "INVALID_CREDENTIALS", "Неверная почта или пароль", "crm");
    }
    if (user.loginError) {
      return failure(
        user.loginError.status,
        user.loginError.code,
        user.loginError.code,
        user.loginError.source,
      );
    }
    // Отключённого в Оргструктуре CRM не отличает от неверного пароля (Q-PLT-10-1).
    if (isEmployeeDisabled(user.id)) {
      return failure(401, "INVALID_CREDENTIALS", "Неверная почта или пароль", "crm");
    }
    const session = buildSession(startSession(user));
    return session ? HttpResponse.json(session) : failure(500, "INTERNAL_ERROR", "Нет сессии");
  }),

  http.post("*/auth/logout", () => {
    endSession();
    return new HttpResponse(null, { status: 204 });
  }),

  http.post("*/auth/change-password", async ({ request }) => {
    const session = readSession();
    if (!session) return sessionExpired();
    const body = (await request.json()) as ChangePasswordIn;
    if (body.current_password === DEMO_WRONG_CURRENT_PASSWORD) {
      return failure(422, "WRONG_PASSWORD", "Текущий пароль неверен", "crm");
    }
    updateSession({ mustChangePassword: false });
    const changed = findUserById(session.userId);
    if (changed) {
      forgetTemporaryPassword(changed.email);
      updateExtraUser(changed.id, { mustChangePassword: false });
    }
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/auth/session", () => {
    const session = readSession();
    const body = session ? buildSession(session) : undefined;
    return body ? HttpResponse.json(body) : sessionExpired();
  }),

  http.get("*/me", () => {
    const session = readSession();
    const me = session ? buildMe(session) : undefined;
    return me ? HttpResponse.json(me) : sessionExpired();
  }),

  http.patch("*/me", async ({ request }) => {
    const current = readSession();
    if (!current) return sessionExpired();
    const body = (await request.json()) as MeUpdate;
    const user = buildMe(current);
    if (body.active_role && !user?.roles.some((role) => role.id === body.active_role)) {
      return failure(422, "VALIDATION_FAILED", "Роль не выдана сотруднику");
    }
    const next = updateSession({
      ...(body.language ? { language: body.language } : {}),
      ...("active_role" in body ? { activeRole: body.active_role ?? null } : {}),
    });
    const me = next ? buildMe(next) : undefined;
    return me ? HttpResponse.json(me) : sessionExpired();
  }),

  ...profileHandlers,
  ...aboutHandlers,
  ...adminUsersHandlers,
  ...adminAuditHandlers,
  ...adminRolesHandlers,
  ...adminIntegrationsHandlers,
  ...adminCompanyHandlers,
  ...adminBusHandlers,
  ...setupHandlers,
  ...botKbHandlers,
  ...crmMessagesHandlers,
  ...crmLeadsHandlers,
  ...bridgeHandlers,
  ...ticketsHandlers,
  ...companyArticlesHandlers,
  // Раньше «Создать документ»: вложения служебок к оплате (счёт поставщика, платёжка) отдаются здесь, остальное — дальше.
  ...edsPaymentsHandlers,
  ...edsDocumentsHandlers,
  ...edsLettersHandlers,
  ...edsApprovalsHandlers,
  ...erpCalcHandlers,
  ...erpStockHandlers,

  getGetHealthMockHandler({
    status: "ok",
    checks: { redis: "ok", crm: "ok", erp: "ok" },
    version: "0.2.0",
  }),

  // Dashboard, уведомления, поиск: данные по роли сессии (PLT-14)
  ...feedHandlers,
  ...eventStreamHandlers,

  ...getRailTechPlatformBFFAPICRMERPMock(),
];
