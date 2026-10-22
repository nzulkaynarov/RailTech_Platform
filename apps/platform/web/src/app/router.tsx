import { Navigate, type RouteObject } from "react-router";

import { AuthGate } from "./auth/AuthGate";
import { ChangePasswordPage } from "./auth/ChangePasswordPage";
import { DEFAULT_HOME } from "./auth/redirect";
import { LoginPage } from "./auth/LoginPage";
import { NotFoundPage } from "./NotFoundPage";
import { AppShell } from "./shell/AppShell";

/**
 * Карта маршрутов (SPEC-v3 §6.3): вход и смена пароля — вне каркаса, шесть модулей — внутри `AppShell`, каждый грузится
 * лениво. Доступ к разделам проверяет `RequireAccess` внутри модуля по `Me.resources`.
 */

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  // Витрина общих компонентов (PLT-13): статическое условие `import.meta.env.DEV` — сборка отбрасывает ветку вместе с
  // модулем, в прод-бандле витрины нет.
  ...(import.meta.env.DEV ? [{ path: "/dev/ui", lazy: () => import("../dev/UiShowcase") }] : []),
  {
    element: <AuthGate />,
    children: [
      { path: "/change-password", element: <ChangePasswordPage /> },
      {
        element: <AppShell />,
        children: [
          { index: true, element: <Navigate to={DEFAULT_HOME} replace /> },
          { path: "dashboard/*", lazy: () => import("../modules/dashboard") },
          { path: "crm/*", lazy: () => import("../modules/crm") },
          { path: "eds/*", lazy: () => import("../modules/eds") },
          { path: "erp/*", lazy: () => import("../modules/erp") },
          { path: "chats/*", lazy: () => import("../modules/chats") },
          { path: "admin/*", lazy: () => import("../modules/admin") },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
