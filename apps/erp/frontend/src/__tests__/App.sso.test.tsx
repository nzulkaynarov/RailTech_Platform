import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import axios, { type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios';

// FIX-58 / D-01: SSO CRM → ERP в чистом браузере (нет cookie, нет access-токена) рвался. App.tsx
// запускал initAuth() на любом маршруте, в том числе на /sso/exchange; параллельный
// GET accounts/users/me/ → 401 → refresh 401 → failRefresh делал logout() и window.location.href='/'
// ровно в момент, когда POST /auth/sso/exchange/ ещё шёл — браузер отменял обмен. Гонка плавающая:
// зависит от того, что медленнее — обмен или me/refresh. Здесь обмен ЗАВЕДОМО медленнее.

import App from '../App';
import { getAccessToken, setAccessToken } from '../api/accessToken';
import { apiClient } from '../api/client';
import { useAuthStore } from '../store/authStore';

const ISSUED = 'issued-by-exchange';
const USER = { id: 7, email: 'sso@example.com', first_name: 'Sso', last_name: 'User', primary_company: { id: 1, name: 'ACME' } };

type Call = { method: string; url: string };

function makeAdapter(calls: Call[]): AxiosAdapter {
  return async (config: InternalAxiosRequestConfig) => {
    const url = String(config.url);
    calls.push({ method: String(config.method), url });
    const reply = (status: number, data: unknown) => {
      const response = { data, status, statusText: String(status), headers: {}, config };
      if (status >= 400) {
        return Promise.reject(Object.assign(new Error(`HTTP ${status}`), { isAxiosError: true, response, config }));
      }
      return Promise.resolve(response);
    };
    if (url.includes('auth/token/refresh')) return reply(401, { detail: 'NO_COOKIE' });
    if (url.includes('auth/logout')) return reply(200, {});
    if (url.includes('accounts/users/me')) {
      const auth = (config.headers as unknown as { Authorization?: string }).Authorization;
      return auth === `Bearer ${ISSUED}` ? reply(200, USER) : reply(401, { detail: 'NOT_AUTHENTICATED' });
    }
    return reply(200, {});
  };
}

describe('SSO exchange vs. фоновая проверка сессии (D-01)', () => {
  const calls: Call[] = [];
  const hrefAssignments: string[] = [];
  const replace = vi.fn();
  let origApiAdapter: typeof apiClient.defaults.adapter;
  let origAxiosAdapter: typeof axios.defaults.adapter;

  beforeEach(() => {
    calls.length = 0;
    hrefAssignments.length = 0;
    replace.mockReset();
    setAccessToken(null);
    useAuthStore.setState({ user: null, accessToken: null, isAuthenticated: false });

    origApiAdapter = apiClient.defaults.adapter;
    origAxiosAdapter = axios.defaults.adapter;
    apiClient.defaults.adapter = makeAdapter(calls);
    axios.defaults.adapter = makeAdapter(calls);

    const loc = {
      pathname: '/sso/exchange',
      search: '',
      hash: '#token=sso-jwt',
      origin: 'http://erp.localhost',
      get href() {
        return 'http://erp.localhost/sso/exchange#token=sso-jwt';
      },
      set href(v: string) {
        hrefAssignments.push(v);
      },
      replace,
    };
    vi.stubGlobal('location', loc);

    // Обмен намного медленнее me/refresh (там мгновенные 401).
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        await new Promise((r) => setTimeout(r, 250));
        return new Response(
          JSON.stringify({ access_token: ISSUED, expires_in: 300, user: { id: 7 } }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );
  });

  afterEach(() => {
    apiClient.defaults.adapter = origApiAdapter;
    axios.defaults.adapter = origAxiosAdapter;
    vi.unstubAllGlobals();
    setAccessToken(null);
  });

  it('обмен, более медленный чем me/refresh, доходит до конца: вход под пользователем обмена', async () => {
    renderWithProviders(<App />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/'), { timeout: 4000 });

    expect(getAccessToken()).toBe(ISSUED);
    expect(useAuthStore.getState().user?.email).toBe('sso@example.com');
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    // Никакого выхода и редиректа на форму входа, пока шёл обмен.
    expect(hrefAssignments).toEqual([]);
    expect(calls.filter((c) => c.url.includes('auth/logout'))).toEqual([]);
    expect(screen.queryByText(/Вход в кабинет|Sign in/i)).toBeNull();
  });
});
