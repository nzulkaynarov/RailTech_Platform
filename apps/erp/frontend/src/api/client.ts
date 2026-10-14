import axios from 'axios';
import i18n from '@/i18n';
import { getAccessToken, setAccessToken } from './accessToken';

const BASE_ENV_URL = import.meta.env.VITE_API_URL || '';
const API_URL = BASE_ENV_URL.endsWith('/api/v1') ? BASE_ENV_URL : `${BASE_ENV_URL}/api/v1`;

export const apiClient = axios.create({
	baseURL: API_URL,
	timeout: 30_000,
	// Send the HttpOnly refresh cookie on auth requests (F2.1). Cookie is path-scoped
	// to /api/v1/auth/, so it only actually rides refresh/logout, not every call.
	withCredentials: true,
	headers: {
		'Content-Type': 'application/json',
	},
});

// JWT Auth Interceptor — attaches the in-memory access token (never localStorage; F2.1)
apiClient.interceptors.request.use((config) => {
	const token = getAccessToken();
	if (token) {
		config.headers.Authorization = `Bearer ${token}`;
	}
	return config;
});

// L0 (spec-bilingual-ru-en): язык запроса. Бэкенд активирует его LocaleMiddleware'ом, поэтому
// ошибки валидации, choices и прочие серверные строки приходят на языке интерфейса. Читаем
// i18n.language ЛЕНИВО в интерсепторе — переключение языка применяется к следующему же запросу
// без пересоздания клиента. Импорт инстанса i18n (а не хука) — модуль вне React-дерева.
apiClient.interceptors.request.use((config) => {
	try {
		const lang = i18n.language?.split('-')[0];
		if (lang) config.headers['Accept-Language'] = lang;
	} catch { /* noop */ }
	return config;
});

// Token refresh mutex — prevents concurrent refresh attempts.
// Queued requests must be settled on BOTH success and failure, otherwise a failed
// refresh leaves every queued request hanging forever (app appears frozen).
let isRefreshing = false;
type RefreshSubscriber = { resolve: (token: string) => void; reject: (err: unknown) => void };
let refreshSubscribers: RefreshSubscriber[] = [];

function onRefreshed(token: string) {
	const subs = refreshSubscribers;
	refreshSubscribers = [];
	subs.forEach((s) => s.resolve(token));
}

function onRefreshFailed(err: unknown) {
	const subs = refreshSubscribers;
	refreshSubscribers = [];
	subs.forEach((s) => s.reject(err));
}

async function failRefresh(err: unknown): Promise<void> {
	// Side-effects only: reject every queued request, log out, bounce to login.
	// The caller returns the rejection so this never throws back into the try/catch.
	onRefreshFailed(err);
	try {
		const { useAuthStore } = await import('../store/authStore');
		useAuthStore.getState().logout();
	} catch {
		localStorage.removeItem('railtech-auth');
	}
	// Don't bounce the user off public, unauthenticated routes (password setup/reset,
	// registration). A background 401 there is expected — there's no session yet — and
	// hard-redirecting to '/' interrupts the flow (e.g. a stale token makes initAuth's
	// /me/ call 401 the moment the setup-password page mounts). Only force a redirect
	// when an authenticated app page actually lost its session.
	const PUBLIC_AUTH_PATHS = new Set(['/setup-password', '/reset-password', '/forgot-password']);
	const path = window.location.pathname;
	if (path !== '/' && !PUBLIC_AUTH_PATHS.has(path)) window.location.href = '/';
}

// Response interceptor for token refresh
apiClient.interceptors.response.use(
	(response) => response,
	async (error) => {
		const originalRequest = error.config;

		// Never try to refresh on the auth endpoints themselves — a 401 from
		// login/refresh/logout means there's no valid session, and refreshing here
		// would loop (logout → 401 → refresh → fail → logout → …).
		const reqUrl: string = originalRequest?.url || '';
		const isAuthEndpoint = reqUrl.includes('auth/token') || reqUrl.includes('auth/logout');

		if (error.response?.status === 401 && originalRequest && !originalRequest._retry && !isAuthEndpoint) {
			originalRequest._retry = true;

			if (isRefreshing) {
				// Another request is already refreshing — queue this one (settled on both paths)
				return new Promise((resolve, reject) => {
					refreshSubscribers.push({
						resolve: (newToken: string) => {
							originalRequest.headers.Authorization = `Bearer ${newToken}`;
							resolve(apiClient(originalRequest));
						},
						reject,
					});
				});
			}

			isRefreshing = true;

			try {
				// Refresh via the HttpOnly cookie (F2.1) — no token in the body, cookie
				// is sent by withCredentials. A 401 here means no/expired cookie → logout.
				const response = await axios.post(
					`${API_URL}/auth/token/refresh/`,
					{},
					{ withCredentials: true },
				);
				const newToken = response.data.access;

				// Update the in-memory holder + store (keeps the request interceptor in sync).
				setAccessToken(newToken);
				const { useAuthStore } = await import('../store/authStore');
				useAuthStore.getState().setTokens(newToken);

				// Notify queued requests, then retry the original
				onRefreshed(newToken);
				originalRequest.headers.Authorization = `Bearer ${newToken}`;
				return apiClient(originalRequest);
			} catch (refreshError) {
				await failRefresh(refreshError);
				return Promise.reject(refreshError);
			} finally {
				isRefreshing = false;
			}
		}

		// Handle 403 Forbidden
		if (error.response?.status === 403) {
			console.warn('[API] Forbidden:', originalRequest?.url);
		}

		return Promise.reject(error);
	}
);

/**
 * Utility: extract a user-friendly error message from Axios errors.
 */
export function getErrorMessage(error: unknown): string {
	if (typeof error === 'object' && error !== null && 'response' in error) {
		const resp = (error as { response?: { status?: number; data?: { detail?: string } } }).response;
		if (resp?.data?.detail) return resp.data.detail;
		if (resp?.status === 403) return 'errors.forbidden';
		if (resp?.status === 404) return 'errors.notFound';
		if (resp?.status && resp.status >= 500) return 'errors.server';
	}
	if (error instanceof Error) return error.message;
	return 'errors.unknown';
}
