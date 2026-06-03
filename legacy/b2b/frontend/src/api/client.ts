import axios from 'axios';

const BASE_ENV_URL = import.meta.env.VITE_API_URL || '';
const API_URL = BASE_ENV_URL.endsWith('/api/v1') ? BASE_ENV_URL : `${BASE_ENV_URL}/api/v1`;

export const apiClient = axios.create({
	baseURL: API_URL,
	timeout: 30_000,
	headers: {
		'Content-Type': 'application/json',
	},
});

// JWT Auth Interceptor — attaches token from localStorage (persisted by zustand)
apiClient.interceptors.request.use((config) => {
	try {
		const raw = localStorage.getItem('railtech-auth');
		if (raw) {
			const parsed = JSON.parse(raw);
			const token = parsed?.state?.accessToken;
			if (token) {
				config.headers.Authorization = `Bearer ${token}`;
			}
		}
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
	if (window.location.pathname !== '/') window.location.href = '/';
}

// Response interceptor for token refresh
apiClient.interceptors.response.use(
	(response) => response,
	async (error) => {
		const originalRequest = error.config;

		if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
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
				const raw = localStorage.getItem('railtech-auth');
				const refreshToken = raw ? JSON.parse(raw)?.state?.refreshToken : null;
				if (!refreshToken) {
					await failRefresh(error);
					return Promise.reject(error);
				}
				const response = await axios.post(`${API_URL}/auth/token/refresh/`, {
					refresh: refreshToken,
				});
				const newToken = response.data.access;

				// Update store via Zustand (keeps state and localStorage in sync)
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
