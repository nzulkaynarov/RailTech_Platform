import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { apiClient } from '../api/client';
import { User } from '../api/accountsApi';

export type UserRole = 'GUEST' | 'CLIENT' | 'SALES_MANAGER' | 'ACCOUNT_MANAGER' | 'ADMIN';
type KYCStatus = 'L1_UNVERIFIED' | 'PROFILE_SUBMITTED' | 'L2_VERIFIED' | 'L3_CONTRACTED' | null;

interface AuthState {
    user: User | null;
    role: UserRole | null;
    kyc_status: KYCStatus;
    accessToken: string | null;
    refreshToken: string | null;
    isLoading: boolean;
    isAuthenticated: boolean;
    error: string | null;

    login: (email: string, password: string) => Promise<void>;
    logout: () => void;
    initAuth: () => Promise<void>;
    setUser: (user: User) => void;
    setTokens: (access: string, refresh?: string) => void;
    clearError: () => void;
}

const API_URL = import.meta.env.VITE_API_URL || '';

export const useAuthStore = create<AuthState>()(
    persist(
        (set, get) => ({
            user: null,
            role: null,
            kyc_status: null,
            accessToken: null,
            refreshToken: null,
            isLoading: false,
            isAuthenticated: false,
            error: null,

            login: async (email: string, password: string) => {
                set({ isLoading: true, error: null });
                try {
                    const response = await fetch(`${API_URL}/api/v1/auth/token/`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, password }),
                    });

                    if (!response.ok) {
                        const err = await response.json().catch(() => ({}));
                        const message = err.detail || 'auth.loginError';
                        set({ error: message });
                        throw new Error(message);
                    }

                    const { access, refresh } = await response.json();
                    set({ accessToken: access, refreshToken: refresh, error: null });

                    // Fetch user profile with the new token
                    await get().initAuth();
                } catch (e) {
                    const message = e instanceof Error ? e.message : 'Ошибка авторизации';
                    set({ error: message });
                    throw e;
                } finally {
                    set({ isLoading: false });
                }
            },

            logout: () => {
                set({
                    user: null,
                    role: null,
                    kyc_status: null,
                    accessToken: null,
                    refreshToken: null,
                    isAuthenticated: false,
                });
            },

            initAuth: async () => {
                const { accessToken } = get();
                if (!accessToken) {
                    set({ isAuthenticated: false, isLoading: false });
                    return;
                }

                set({ isLoading: true });
                try {
                    // Use apiClient which has the refresh interceptor —
                    // if the access token is expired, it will automatically
                    // refresh using the stored refresh token before retrying
                    const response = await apiClient.get<User>('accounts/users/me/');
                    const user = response.data;
                    get().setUser(user);
                    set({ isAuthenticated: true });
                } catch {
                    // Both access and refresh tokens invalid — logout
                    get().logout();
                } finally {
                    set({ isLoading: false });
                }
            },

            setUser: (user: User) => {
                // Use role_code if available, fallback to role as string if it was somehow passed that way
                const rawRole = user.role_code || (user.role as unknown as string) || 'CLIENT';
                const role = (rawRole === 'MANAGER' ? 'SALES_MANAGER' : rawRole) as UserRole;

                // Backend returns `primary_company`, frontend expects `company`
                const apiUser = user as User & { primary_company?: typeof user.company };
                if (apiUser.primary_company && !user.company) {
                    user.company = apiUser.primary_company;
                }

                set({
                    user,
                    role,
                    kyc_status: (user.kyc_status as KYCStatus) || null,
                });
            },

            setTokens: (access: string, refresh?: string) => {
                const updates: Partial<AuthState> = { accessToken: access };
                if (refresh) updates.refreshToken = refresh;
                set(updates);
            },

            clearError: () => set({ error: null }),
        }),
        {
            name: 'railtech-auth',
            partialize: (state) => ({
                accessToken: state.accessToken,
                refreshToken: state.refreshToken,
                isAuthenticated: state.isAuthenticated,
                role: state.role,
                user: state.user, // Persist user info for immediate display while re-fetching
            }),
        }
    )
);
