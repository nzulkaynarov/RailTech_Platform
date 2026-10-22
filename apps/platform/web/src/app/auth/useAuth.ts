import { createContext, useContext } from "react";

import type { Me } from "../../shared/api/generated/model";

export interface AuthState {
  me: Me;
  mustChangePassword: boolean;
}

export const AuthContext = createContext<AuthState | null>(null);

/** Профиль и признак обязательной смены пароля; доступен под `AuthGate`. */
export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth вне AuthGate");
  return value;
}
