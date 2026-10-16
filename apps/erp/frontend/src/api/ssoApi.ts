import { apiClient } from './client';

export interface SsoTokenResponse {
  token: string;
  redirect_url: string;
}

export interface SsoExchangeResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: Record<string, unknown>;
}

export async function issueSsoToken(): Promise<SsoTokenResponse> {
  const res = await apiClient.post<SsoTokenResponse>('auth/sso/token/');
  return res.data;
}

export async function exchangeSsoToken(token: string): Promise<SsoExchangeResponse> {
  const base = import.meta.env.VITE_API_URL || '';
  const apiUrl = base.endsWith('/api/v1') ? base : `${base}/api/v1`;
  const res = await fetch(`${apiUrl}/auth/sso/exchange/`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail || 'SSO_EXCHANGE_FAILED');
  }
  return res.json() as Promise<SsoExchangeResponse>;
}
