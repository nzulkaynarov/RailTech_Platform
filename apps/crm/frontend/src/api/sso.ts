import { http, tokenStore } from "./http";

export interface SsoTokenResponse {
  token: string;
  redirect_url: string;
}

export interface SsoExchangeResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  must_change_password: boolean;
}

/**
 * Запросить SSO-токен для перехода в ERP под текущей сессией CRM (CONTRACTS §6, M3-CRM-06).
 */
export async function issueSsoToken(): Promise<SsoTokenResponse> {
  return http<SsoTokenResponse>("/api/v1/auth/sso/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Обменять SSO-токен из ERP на сессию CRM (CONTRACTS §6, M3-CRM-06).
 */
export async function exchangeSsoToken(token: string): Promise<SsoExchangeResponse> {
  const response = await fetch("/api/v1/auth/sso/exchange", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!response.ok) {
    const err = (await response.json().catch(() => ({}))) as {
      code?: string;
      message?: string;
    };
    throw new Error(err.message || err.code || "SSO_EXCHANGE_FAILED");
  }
  const data = (await response.json()) as SsoExchangeResponse;
  tokenStore.set(data.access_token);
  return data;
}
