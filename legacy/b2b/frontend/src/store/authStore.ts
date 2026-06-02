import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { apiClient } from '../api/client';
import { User } from '../api/accountsApi';

// Backend SystemRole vocabulary after migration accounts/0010_platform_admin_model.
// Only ADMIN (Platform Admin — owns the platform, not attached to any company)
// and USER (everyone else; their actual permissions come from CompanyMember.role
// = WorkspaceRole within their company). Legacy MANAGER / SALES_MANAGER /
// ACCOUNT_MANAGER / GUEST / CLIENT no longer exist as SystemRoles — see ADR-0002.
export type UserRole = 'ADMIN' | 'USER';
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
                    const response = await fetch(`${API_URL}/auth/token/`, {
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
                    const message = e instanceof Error ? e.message : 'auth.genericError';
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
                // Backend returns either 'ADMIN' or 'USER' (see migration 0010);
                // anything else from older builds is collapsed to 'USER' so the
                // typed literal never goes undefined downstream.
                const rawRole = user.role_code ?? '';
                const role: UserRole = rawRole === 'ADMIN' ? 'ADMIN' : 'USER';

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
