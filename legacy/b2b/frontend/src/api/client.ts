import axios from 'axios';

const BASE_ENV_URL = import.meta.env.VITE_API_URL || '';
const API_URL = BASE_ENV_URL.endsWith('/api/v1') ? BASE_ENV_URL : `${BASE_ENV_URL}/api/v1`;

export const apiClient = axios.create({
	baseURL: API_URL,
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

// Token refresh mutex — prevents concurrent refresh attempts
let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

function onRefreshed(token: string) {
	refreshSubscribers.forEach((cb) => cb(token));
	refreshSubscribers = [];
}

function addRefreshSubscriber(cb: (token: string) => void) {
	refreshSubscribers.push(cb);
}

// Response interceptor for token refresh
apiClient.interceptors.response.use(
	(response) => response,
	async (error) => {
		const originalRequest = error.config;

		if (error.response?.status === 401 && !originalRequest._retry) {
			originalRequest._retry = true;

			if (isRefreshing) {
				// Another request is already refreshing — queue this one
				return new Promise((resolve) => {
					addRefreshSubscriber((newToken: string) => {
						originalRequest.headers.Authorization = `Bearer ${newToken}`;
						resolve(apiClient(originalRequest));
					});
				});
			}

			isRefreshing = true;

			try {
				const raw = localStorage.getItem('railtech-auth');
				if (raw) {
					const authData = JSON.parse(raw);
					const refreshToken = authData?.state?.refreshToken;
					if (refreshToken) {
						const response = await axios.post(`${API_URL}/auth/token/refresh/`, {
							refresh: refreshToken,
						});
						const newToken = response.data.access;

						// Update store
						authData.state.accessToken = newToken;
						localStorage.setItem('railtech-auth', JSON.stringify(authData));

						// Notify queued requests
						onRefreshed(newToken);

						// Retry original request
						originalRequest.headers.Authorization = `Bearer ${newToken}`;
						return apiClient(originalRequest);
					}
				}
			} catch (refreshError) {
				// Refresh failed, logout user
				refreshSubscribers = [];
				localStorage.removeItem('railtech-auth');
				window.location.href = '/';
				return Promise.reject(refreshError);
			} finally {
				isRefreshing = false;
			}
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
