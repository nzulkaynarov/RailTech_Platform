import { HttpResponse, http } from "msw";

import type { SecondFactorCodeIn, SecondFactorLoginIn } from "../shared/api/generated/model";
import { readSession } from "./mockSession";

/**
 * Второй фактор на моках (ДВ-4): код из приложения — `123456`, резервные коды выдаются при включении. Состояние — в
 * `localStorage` по id сотрудника; «запомнить устройство» — отметка там же. Вход по паролю у сотрудника с фактором —
 * 202 с `challenge` (закодированный id), второй шаг — `secondFactorLogin` (вызывает обработчик входа).
 */
export const MOCK_TOTP_CODE = "123456";
const KEY = "rt-pf-mock-2fa";

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

function stateOf(userId: string): FactorState {
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
    return HttpResponse.json({
      enabled: state.enabled,
      enabled_at: state.enabledAt,
      backup_codes_left: state.backup.length,
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
    if (code !== MOCK_TOTP_CODE && !state.backup.includes(code)) {
      return invalid("second_factor_code_invalid");
    }
    write(session.userId, { enabled: false, enabledAt: null, backup: [], remembered: false });
    return new HttpResponse(null, { status: 204 });
  }),
];
