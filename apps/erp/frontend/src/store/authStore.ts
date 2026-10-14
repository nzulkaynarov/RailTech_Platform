import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { apiClient } from '../api/client';
import { setAccessToken } from '../api/accessToken';
import { User } from '../api/accountsApi';
import { queryClient } from '../lib/queryClient';

interface AuthState {
    user: User | null;
    // Access token is held in memory only (see api/accessToken.ts); the refresh
    // token lives in an HttpOnly cookie the server sets — never in JS (F2.1).
    accessToken: string | null;
    isLoading: boolean;
    isAuthenticated: boolean;
    error: string | null;

    login: (email: string, password: string) => Promise<{ twoFactorRequired: boolean; tempToken?: string } | void>;
    login2FA: (tempToken: string, code: string) => Promise<void>;
    logout: () => Promise<void>;
    initAuth: () => Promise<void>;
    setUser: (user: User) => void;
    setTokens: (access: string) => void;
    clearError: () => void;
}

// Mirror api/client.ts: ensure the /api/v1 prefix regardless of whether
// VITE_API_URL is "/api" or already "/api/v1". Login uses raw fetch (NOT apiClient)
// on purpose — a 401 here means bad credentials and must NOT trigger the token-
// refresh interceptor (which would redirect to login instead of showing the error).
const _BASE = import.meta.env.VITE_API_URL || '';
const API_URL = _BASE.endsWith('/api/v1') ? _BASE : `${_BASE}/api/v1`;

export const useAuthStore = create<AuthState>()(
    persist(
        (set, get) => ({
            user: null,
            accessToken: null,
            isLoading: false,
            isAuthenticated: false,
            error: null,

            login: async (email: string, password: string) => {
                set({ isLoading: true, error: null });
                try {
                    const response = await fetch(`${API_URL}/auth/token/`, {
                        method: 'POST',
                        // credentials: include → accept the HttpOnly refresh cookie the server sets.
                        credentials: 'include',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, password }),
                    });

                    if (!response.ok) {
                        const err = await response.json().catch(() => ({}));
                        const message = err.detail || 'auth.loginError';
                        set({ error: message });
                        throw new Error(message);
                    }

                    // Only the access token comes back in the body; refresh is in the cookie.
                    const data = await response.json() as { '2fa_required'?: boolean; temp_token?: string; access?: string };
                    if (data['2fa_required']) {
                        return { twoFactorRequired: true, tempToken: data.temp_token };
                    }

                    const access = data.access;
                    if (!access) {
                        throw new Error('auth.invalidResponse');
                    }
                    setAccessToken(access);
                    set({ accessToken: access, error: null });

                    // SHARED-BROWSER SAFETY: wipe any prior user's cached queries before the
                    // new identity's data loads — otherwise refetchOnMount:false + staleTime
                    // would serve the previous tenant's ['deals']/['quotes']/analytics rows.
                    queryClient.clear();

                    // Fetch user profile with the new token
                    await get().initAuth();
                    return { twoFactorRequired: false };
                } catch (e) {
                    const message = e instanceof Error ? e.message : 'auth.genericError';
                    set({ error: message });
                    throw e;
                } finally {
                    set({ isLoading: false });
                }
            },

            login2FA: async (tempToken: string, code: string) => {
                set({ isLoading: true, error: null });
                try {
                    const response = await fetch(`${API_URL}/auth/login/2fa/`, {
                        method: 'POST',
                        credentials: 'include',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ temp_token: tempToken, code }),
                    });

                    if (!response.ok) {
                        const err = await response.json().catch(() => ({}));
                        const message = err.detail || 'auth.invalid2faCode';
                        set({ error: message });
                        throw new Error(message);
                    }

                    const { access } = await response.json() as { access: string };
                    setAccessToken(access);
                    set({ accessToken: access, error: null });

                    queryClient.clear();
                    await get().initAuth();
                } catch (e) {
                    const message = e instanceof Error ? e.message : 'auth.genericError';
                    set({ error: message });
                    throw e;
                } finally {
                    set({ isLoading: false });
                }
            },

            logout: async () => {
                // MUST await: the server clears the HttpOnly refresh cookie. If we
                // redirect before that, the reload's initAuth re-mints an access token
                // from the still-present cookie → "logout doesn't work" (re-logged-in).
                try {
                    await apiClient.post('auth/logout/');
                } catch { /* even if it fails, clear locally below */ }
                setAccessToken(null);
                set({
                    user: null,
                    accessToken: null,
                    isAuthenticated: false,
                });
                // Drop every cached query so the next user on this browser starts clean
                // (cross-tenant cache-leak guard — pairs with the clear() on login).
                queryClient.clear();
            },

            initAuth: async () => {
                set({ isLoading: true });
                try {
                    // Access token is in-memory only, so after a reload there is none. Do NOT
                    // refresh here with a raw fetch — that bypasses the apiClient refresh mutex,
                    // so it races against the interceptor refresh that any other component's
                    // API call (firing on mount before this resolves) triggers. With rotation +
                    // blacklist on, two concurrent refreshes mean one blacklists the other's
                    // token → 401 → the user is logged out on reload (latency makes this bite on
                    // prod even when it passes locally). Instead, just call /me: the FIRST 401
                    // mints a fresh access via the single mutex'd interceptor refresh, and every
                    // concurrent call queues on it — exactly one refresh, no race (F2.1).
                    const response = await apiClient.get<User>('accounts/users/me/');
                    get().setUser(response.data);
                    set({ isAuthenticated: true });
                } catch {
                    // No valid session (the interceptor's cookie refresh failed). Clear locally;
                    // don't call logout() — that POSTs auth/logout/ needlessly and the interceptor
                    // already handled the redirect for a genuinely expired session.
                    setAccessToken(null);
                    set({ isAuthenticated: false, user: null });
                } finally {
                    set({ isLoading: false });
                }
            },

            setUser: (user: User) => {
                // Backend returns `primary_company`, frontend expects `company`
                const apiUser = user as User & { primary_company?: typeof user.company };
                if (apiUser.primary_company && !user.company) {
                    user.company = apiUser.primary_company;
                }

                set({ user });
            },

            setTokens: (access: string) => {
                setAccessToken(access);
                set({ accessToken: access });
            },

            clearError: () => set({ error: null }),
        }),
        {
            name: 'railtech-auth',
            // Tokens are NEVER persisted (F2.1): access is in-memory, refresh is an
            // HttpOnly cookie. Only cache display data so the shell paints instantly on
            // reload while initAuth() re-mints the access token from the cookie.
            partialize: (state) => ({
                isAuthenticated: state.isAuthenticated,
                user: state.user,
            }),
        }
    )
);
