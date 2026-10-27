import type { RouteObject } from "react-router";

import { HomeRedirect } from "./HomeRedirect";

import { AuthGate } from "./auth/AuthGate";
import { ChangePasswordPage } from "./auth/ChangePasswordPage";
import { LoginPage } from "./auth/LoginPage";
import { SetupPage } from "./auth/SetupPage";
import { NotFoundPage } from "./NotFoundPage";
import { AppShell } from "./shell/AppShell";
import { PanelSlotProvider } from "./shell/PanelSlot";

/**
 * Карта маршрутов (SPEC-v3 §6.3): вход и смена пароля — вне каркаса, шесть модулей — внутри `AppShell`, каждый грузится
 * лениво. Доступ к разделам проверяет `RequireAccess` внутри модуля по `Me.resources`.
 */

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  // «Первый запуск» до входа (W13-A4): пока в CRM нет администратора, вход ведёт сюда.
  { path: "/setup", element: <SetupPage /> },
  // Витрина общих компонентов (PLT-13): статическое условие `import.meta.env.DEV` — сборка отбрасывает ветку вместе с
  // модулем, в прод-бандле витрины нет.
  ...(import.meta.env.DEV ? [{ path: "/dev/ui", lazy: () => import("../dev/UiShowcase") }] : []),
  {
    element: <AuthGate />,
    children: [
      { path: "/change-password", element: <ChangePasswordPage /> },
      {
        element: (
          <PanelSlotProvider>
            <AppShell />
          </PanelSlotProvider>
        ),
        children: [
          { index: true, element: <HomeRedirect /> },
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
