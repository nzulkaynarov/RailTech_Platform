import { HttpResponse, http } from "msw";

import type { Bridge } from "../shared/api/generated/model";
import { buildMe, readSession } from "./mockSession";

/**
 * Мост в старые экраны для MSW (W15-H1, BFF 0.18.0). По умолчанию адреса — как на стенде ансамбля (`*.localhost`), вход в
 * старый ERP по SSO доступен тем, у кого есть доступ к ERP. Сценарии «адреса нет» и «SSO не вышел» включает запись в
 * `localStorage` страницы до загрузки (e2e) или `setBridgeMock` (тесты).
 */
const KEY = "rt-pf-mock-bridge";

export interface BridgeMock {
  crmUrl: string | null;
  erpUrl: string | null;
  /** SSO в ERP отвечает ошибкой (CRM отказала или не отвечает) */
  ssoFails: boolean;
}

const DEFAULTS: BridgeMock = {
  crmUrl: "http://crm.localhost:8088",
  erpUrl: "http://erp.localhost:8088",
  ssoFails: false,
};

export function readBridgeMock(): BridgeMock {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as Partial<BridgeMock>) } : DEFAULTS;
  } catch {
    return DEFAULTS;
  }
}

export function setBridgeMock(patch: Partial<BridgeMock> | null): void {
  try {
    if (patch === null) window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, JSON.stringify({ ...readBridgeMock(), ...patch }));
  } catch {
    // Без хранилища остаются значения по умолчанию.
  }
}

function hasErp(): boolean {
  const session = readSession();
  return session ? (buildMe(session)?.access.erp ?? false) : false;
}

export const bridgeHandlers = [
  http.get("*/bridge", () => {
    const state = readBridgeMock();
    const body: Bridge = { crm_url: state.crmUrl, erp_url: state.erpUrl, erp_sso: hasErp() };
    return HttpResponse.json(body, { headers: { "Cache-Control": "no-store" } });
  }),
  http.post("*/bridge/erp-sso", () => {
    const state = readBridgeMock();
    if (state.ssoFails || !hasErp()) {
      return HttpResponse.json(
        {
          code: "FORBIDDEN",
          message: "Вход в старый ERP без второго пароля недоступен.",
          source: "crm",
          details: { reason: "sso_disabled" },
        },
        { status: 403 },
      );
    }
    const base = state.erpUrl ?? "http://erp.localhost:8088";
    return HttpResponse.json({ url: `${base}/sso/exchange#token=mock-one-time-token` });
  }),
];
