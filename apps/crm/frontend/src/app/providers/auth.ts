import type { AuthProvider } from "@refinedev/core";

import { ApiError, refreshAccess, tokenStore, unwrap } from "../../api/http";
import { login, logout, me } from "../../api/generated/crm";
import { errorText, t } from "../../i18n/ru";

/** Признак обязательной смены пароля: роутер уводит на /change-password. */
export const passwordChange = { required: false };

export const authProvider: AuthProvider = {
  async login({ email, password }: { email: string; password: string }) {
    try {
      const data = unwrap(await login({ email, password }));
      tokenStore.set(data.access_token);
      passwordChange.required = data.must_change_password;
      return { success: true, redirectTo: data.must_change_password ? "/change-password" : "/" };
    } catch (error) {
      const code = error instanceof ApiError ? error.code : undefined;
      const message = code === "account_locked" ? t.auth.locked : t.auth.invalid;
      return { success: false, error: { name: t.auth.title, message } };
    }
  },
  async logout() {
    try {
      await logout();
    } finally {
      tokenStore.set(null);
    }
    return { success: true, redirectTo: "/login" };
  },
  async check() {
    if (tokenStore.get() || (await refreshAccess())) return { authenticated: true };
    return { authenticated: false, redirectTo: "/login", logout: true };
  },
  async getIdentity() {
    try {
      const data = unwrap(await me());
      passwordChange.required = data.must_change_password;
      return { ...data, name: data.full_name };
    } catch {
      return null;
    }
  },
  onError(error: unknown) {
    if (error instanceof ApiError && error.status === 401) {
      return Promise.resolve({ logout: true, redirectTo: "/login" });
    }
    if (error instanceof ApiError && error.code === "password_change_required") {
      return Promise.resolve({ redirectTo: "/change-password" });
    }
    const code = error instanceof ApiError ? error.code : undefined;
    return Promise.resolve({ error: { name: t.errors.generic ?? "", message: errorText(code) } });
  },
};
