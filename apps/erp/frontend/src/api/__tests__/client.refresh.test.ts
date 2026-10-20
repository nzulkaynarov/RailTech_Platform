import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import axios, { type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios';
import { apiClient } from '../client';
import { getAccessToken, setAccessToken } from '../accessToken';

// FIX-58 / D-01: failRefresh не должен сбрасывать сессию, выданную, пока шёл refresh
// (SSO-обмен, вход), и не должен трогать logout/редирект на /sso/exchange.

const calls: string[] = [];
const hrefAssignments: string[] = [];

function reject(config: InternalAxiosRequestConfig, status: number) {
  const response = { data: {}, status, statusText: String(status), headers: {}, config };
  return Promise.reject(Object.assign(new Error(`HTTP ${status}`), { isAxiosError: true, response, config }));
}

describe('apiClient: провал refresh', () => {
  let origApi: typeof apiClient.defaults.adapter;
  let origAxios: typeof axios.defaults.adapter;

  function setup(pathname: string, onRefresh?: () => void) {
    vi.stubGlobal('location', {
      pathname,
      get href() {
        return `http://erp.localhost${pathname}`;
      },
      set href(v: string) {
        hrefAssignments.push(v);
      },
    });
    const adapter: AxiosAdapter = async (config) => {
      const url = String(config.url);
      calls.push(url);
      if (url.includes('auth/token/refresh')) {
        onRefresh?.();
        return reject(config, 401);
      }
      if (url.includes('auth/logout')) return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
      return reject(config, 401);
    };
    apiClient.defaults.adapter = adapter;
    axios.defaults.adapter = adapter;
  }

  beforeEach(() => {
    calls.length = 0;
    hrefAssignments.length = 0;
    setAccessToken(null);
    origApi = apiClient.defaults.adapter;
    origAxios = axios.defaults.adapter;
  });
  afterEach(() => {
    apiClient.defaults.adapter = origApi;
    axios.defaults.adapter = origAxios;
    vi.unstubAllGlobals();
    setAccessToken(null);
  });

  it('на /sso/exchange 401 + провал refresh: ни logout, ни редиректа', async () => {
    setup('/sso/exchange');
    await expect(apiClient.get('accounts/users/me/')).rejects.toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(calls.some((u) => u.includes('auth/logout'))).toBe(false);
    expect(hrefAssignments).toEqual([]);
  });

  it('токен выдан, пока шёл refresh (вход/обмен): провал refresh его не сбрасывает', async () => {
    setup('/deals', () => setAccessToken('fresh-from-login'));
    await expect(apiClient.get('crm/deals/')).rejects.toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(getAccessToken()).toBe('fresh-from-login');
    expect(calls.some((u) => u.includes('auth/logout'))).toBe(false);
    expect(hrefAssignments).toEqual([]);
  });

  it('обычная страница без сессии: выход и редирект на / как раньше', async () => {
    setup('/deals');
    await expect(apiClient.get('crm/deals/')).rejects.toBeTruthy();
    await vi.waitFor(() => expect(hrefAssignments).toEqual(['/']));
    expect(calls.some((u) => u.includes('auth/logout'))).toBe(true);
  });
});
