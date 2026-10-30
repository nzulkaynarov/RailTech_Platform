import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";

import { AppProviders } from "../app/providers";
import { createQueryClient } from "../app/queryClient";
import { routes } from "../app/router";
import { findUser } from "../mocks/fixtures/users";
import { startSession, updateSession } from "../mocks/mockSession";
import { ROLE_ID, type PresetCode } from "../mocks/fixtures/roles";

/** Всё приложение (каркас, маршруты, MSW-моки) по адресу: для тестов экранов, которым нужен каркас и сессия. */
export function renderApp(path: string) {
  // Клиент приложения (прежние данные при смене фильтра — `keepSamePathData`, UX-1c) без повторов и кэша свежести.
  const queryClient = createQueryClient({ retry: false, staleTime: 0 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { router, queryClient };
}

/** Вход демо-сотрудника без экрана «Вход»; `activeRole` — выбранная в меню аватара роль («вид»). */
export function signInAs(email: string, activeRole?: PresetCode): void {
  const user = findUser(email);
  if (!user) throw new Error(`нет демо-пользователя ${email}`);
  startSession(user);
  if (activeRole) updateSession({ activeRole: ROLE_ID[activeRole] });
}
