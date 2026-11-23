import { HttpResponse, http } from "msw";

import type {
  EnrollIn,
  EnrollSetupIn,
  SecondFactorCodeIn,
  SecondFactorLoginIn,
} from "../shared/api/generated/model";
import { effectiveRoleIds } from "./fixtures/employees";
import { ROLE_ID, computeAccess, readRoles, rolesOf } from "./fixtures/roles";
import { type DemoUser, findUserById } from "./fixtures/users";
import { readSession } from "./mockSession";

/**
 * Второй фактор на моках (ДВ-4): код из приложения — `123456`, резервные коды выдаются при включении. Состояние — в
 * `localStorage` по id сотрудника; «запомнить устройство» — отметка там же. Вход по паролю у сотрудника с фактором —
 * 202 с `challenge` (закодированный id), второй шаг — `secondFactorLogin` (вызывает обработчик входа).
 */
export const MOCK_TOTP_CODE = "123456";
const KEY = "rt-pf-mock-2fa";

/**
 * Сценарии ДВ-4б включаются ключами `localStorage` до входа — остальные сценарии (входят директором, бухгалтером,
 * администратором по паролю) идут как раньше:
 * - `rt-pf-mock-2fa-required = "1"` — фактор обязателен держателям разделов с деньгами и доступом: вход без фактора —
 *   202 с `enrollment_required`, отключить фактор нельзя;
 * - `rt-pf-mock-step-up = "1"` — выдача роли и подтверждение реквизитов требуют свежий код (`X-Step-Up-Token`).
 */
const REQUIRED_KEY = "rt-pf-mock-2fa-required";
const STEP_UP_KEY = "rt-pf-mock-step-up";
const STEP_UP_TOKEN = "mock-step-up-token";
/** Те же разделы, что `FACTOR_REQUIRED_SECTIONS` в CRM (`domain/second_factor_policy.py`): полный уровень. */
const REQUIRED_SECTIONS = ["eds.payments", "eds.memo.approve", "eds.drafts", "admin"] as const;

function flag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

/** Обязателен ли фактор сотруднику: по разделам его ролей, не по названию роли. */
export function factorRequired(user: DemoUser): boolean {
  if (!flag(REQUIRED_KEY)) return false;
  const ids = effectiveRoleIds(
    user.id,
    user.roles.map((code) => ROLE_ID[code]),
  );
  const { resources } = computeAccess(rolesOf(ids, readRoles()));
  return REQUIRED_SECTIONS.some((section) => resources[section] === "full");
}

/** Фактор обязателен, но не настроен — входу нужна настройка. */
export function needsEnrollment(user: DemoUser): boolean {
  return factorRequired(user) && !stateOf(user.id).enabled;
}

export const enrollChallengeOf = (userId: string): string => btoa(`enroll:${userId}`);

function enrollUser(challenge: string): DemoUser | undefined {
  try {
    return findUserById(atob(challenge).replace(/^enroll:/, ""));
  } catch {
    return undefined;
  }
}

/** Свежий код: сценарий включён, а токена нет — 403, как у BFF. */
export function stepUpRefusal(request: Request): Response | null {
  if (!flag(STEP_UP_KEY)) return null;
  if (request.headers.get("x-step-up-token") === STEP_UP_TOKEN) return null;
  const session = readSession();
  const enrolled = session ? stateOf(session.userId).enabled : false;
  return HttpResponse.json(
    {
      code: "STEP_UP_REQUIRED",
      message: "Введите свежий код.",
      source: "crm",
      details: { reason: enrolled ? "step_up_required" : "second_factor_not_enrolled" },
    },
    { status: 403 },
  );
}

interface FactorState {
  enabled: boolean;
  enabledAt: string | null;
  backup: string[];
  remembered: boolean;
}

function readAll(): Record<string, FactorState> {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Record<string, FactorState>;
  } catch {
    return {};
  }
}

function write(userId: string, state: FactorState): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...readAll(), [userId]: state }));
  } catch {
    // без localStorage — только на эту загрузку
  }
}

export function stateOf(userId: string): FactorState {
  return readAll()[userId] ?? { enabled: false, enabledAt: null, backup: [], remembered: false };
}

/** Нужен ли второй шаг: фактор включён и устройство не запомнено. */
export function needsSecondFactor(userId: string): boolean {
  const state = stateOf(userId);
  return state.enabled && !state.remembered;
}

export const challengeOf = (userId: string): string => btoa(`2fa:${userId}`);

/** Второй шаг: сотрудник по `challenge` или ошибка входа. */
export function acceptSecondFactor(
  body: SecondFactorLoginIn,
): { userId: string } | { error: "SECOND_FACTOR_INVALID" | "SECOND_FACTOR_EXPIRED" } {
  let userId: string;
  try {
    userId = atob(body.challenge).replace(/^2fa:/, "");
  } catch {
    return { error: "SECOND_FACTOR_EXPIRED" };
  }
  const state = stateOf(userId);
  if (!state.enabled) return { error: "SECOND_FACTOR_EXPIRED" };
  const code = body.code.trim().toUpperCase();
  if (code !== MOCK_TOTP_CODE) {
    if (!state.backup.includes(code)) return { error: "SECOND_FACTOR_INVALID" };
    state.backup = state.backup.filter((item) => item !== code);
  }
  write(userId, { ...state, remembered: state.remembered || Boolean(body.remember_device) });
  return { userId };
}

const BACKUP = [
  "4F7K-92QD",
  "8MZP-1LX3",
  "T6WN-5RHC",
  "2BQV-JD84",
  "K9EF-7SGA",
  "R3YU-0PMN",
  "H7CA-QW2E",
  "N4XB-6TDZ",
];

function invalid(reason: string) {
  return HttpResponse.json(
    { code: "VALIDATION_FAILED", message: "Неверный код.", source: "crm", details: { reason } },
    { status: 422 },
  );
}

export const secondFactorHandlers = [
  http.get("*/me/second-factor", () => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const state = stateOf(session.userId);
    const user = findUserById(session.userId);
    return HttpResponse.json({
      enabled: state.enabled,
      enabled_at: state.enabledAt,
      backup_codes_left: state.backup.length,
      required: user ? factorRequired(user) : false,
    });
  }),
  http.post("*/me/second-factor/setup", () => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    if (stateOf(session.userId).enabled) return invalid("second_factor_already_enabled");
    const secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
    return HttpResponse.json({
      secret,
      otpauth_uri: `otpauth://totp/Demo:${encodeURIComponent(session.userId)}?secret=${secret}&issuer=Demo`,
    });
  }),
  http.post("*/me/second-factor/enable", async ({ request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const body = (await request.json()) as SecondFactorCodeIn;
    if (body.code.trim() !== MOCK_TOTP_CODE) return invalid("second_factor_code_invalid");
    write(session.userId, {
      enabled: true,
      enabledAt: new Date().toISOString(),
      backup: [...BACKUP],
      remembered: false,
    });
    return HttpResponse.json({ backup_codes: BACKUP });
  }),
  http.post("*/me/second-factor/disable", async ({ request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const body = (await request.json()) as SecondFactorCodeIn;
    const state = stateOf(session.userId);
    const code = body.code.trim().toUpperCase();
    const me = findUserById(session.userId);
    if (me && factorRequired(me)) {
      return HttpResponse.json(
        {
          code: "CONFLICT",
          message: "Для вашего доступа второй фактор обязателен.",
          source: "crm",
          details: { reason: "second_factor_required" },
        },
        { status: 409 },
      );
    }
    if (code !== MOCK_TOTP_CODE && !state.backup.includes(code)) {
      return invalid("second_factor_code_invalid");
    }
    write(session.userId, { enabled: false, enabledAt: null, backup: [], remembered: false });
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/me/second-factor/step-up", async ({ request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const body = (await request.json()) as SecondFactorCodeIn;
    if (!stateOf(session.userId).enabled) {
      return HttpResponse.json(
        {
          code: "STEP_UP_REQUIRED",
          message: "Фактор не включён.",
          source: "crm",
          details: { reason: "second_factor_not_enrolled" },
        },
        { status: 403 },
      );
    }
    if (body.code.trim() !== MOCK_TOTP_CODE) return invalid("second_factor_code_invalid");
    return HttpResponse.json({ token: STEP_UP_TOKEN, expires_in: 300 });
  }),
  http.post("*/auth/login/enroll/setup", async ({ request }) => {
    const body = (await request.json()) as EnrollSetupIn;
    const user = enrollUser(body.challenge);
    if (!user) return expired();
    const secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
    return HttpResponse.json({
      secret,
      otpauth_uri: `otpauth://totp/Demo:${encodeURIComponent(user.id)}?secret=${secret}&issuer=Demo`,
    });
  }),
  http.post("*/admin/users/:id/second-factor/reset", async ({ params, request }) => {
    const session = readSession();
    if (!session) return new HttpResponse(null, { status: 401 });
    const body = (await request.json()) as { reason: string };
    if (params["id"] === session.userId) {
      return HttpResponse.json(
        {
          code: "CONFLICT",
          message: "Свой фактор меняет другой администратор.",
          source: "bff",
          details: { reason: "second_factor_self_reset" },
        },
        { status: 409 },
      );
    }
    if (body.reason.trim().length < 3) return invalid("reason_required");
    write(String(params["id"]), { enabled: false, enabledAt: null, backup: [], remembered: false });
    return new HttpResponse(null, { status: 204 });
  }),
];

function expired() {
  return HttpResponse.json(
    {
      code: "SECOND_FACTOR_EXPIRED",
      message: "Время вышло.",
      source: "crm",
    },
    { status: 401 },
  );
}

/** Настройка при входе (ДВ-4б): код верен — фактор включён, сотрудник — по `challenge`; резервные коды — один раз. */
export function acceptEnrollment(
  body: EnrollIn,
):
  | { user: DemoUser; backup: string[] }
  | { error: "SECOND_FACTOR_INVALID" | "SECOND_FACTOR_EXPIRED" } {
  const user = enrollUser(body.challenge);
  if (!user) return { error: "SECOND_FACTOR_EXPIRED" };
  if (body.code.trim() !== MOCK_TOTP_CODE) return { error: "SECOND_FACTOR_INVALID" };
  write(user.id, {
    enabled: true,
    enabledAt: new Date().toISOString(),
    backup: [...BACKUP],
    remembered: false,
  });
  return { user, backup: [...BACKUP] };
}
