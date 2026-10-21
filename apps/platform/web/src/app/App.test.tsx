import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { getGetHealthMockHandler } from "../shared/api/generated/platform-bff.msw";
import { server } from "../test/server";
import { AppProviders } from "./providers";
import { routes } from "./router";

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/"] });
  return render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

describe("страница-заглушка P0", () => {
  it("показывает заголовок и статус из getHealth (ok)", async () => {
    renderApp();

    expect(screen.getByRole("heading", { level: 1, name: "Платформа — каркас P0" })).toBeVisible();
    expect(await screen.findByText("Работает")).toBeVisible();
    expect(screen.getByText("Redis (сессии)")).toBeVisible();
  });

  it("показывает degraded словом, а не только цветом", async () => {
    server.use(
      getGetHealthMockHandler({
        status: "degraded",
        checks: { redis: "ok", crm: "fail", erp: "fail" },
      }),
    );
    renderApp();

    const status = await screen.findByTestId("health-status");
    expect(within(status).getByText("Работает не полностью")).toBeVisible();
    expect(screen.getAllByText("Недоступен")).toHaveLength(2);
  });

  it("при ошибке BFF показывает сообщение и кнопку повтора", async () => {
    const { HttpResponse, http } = await import("msw");
    server.use(
      http.get("*/health", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "Нет связи", source: "bff" },
          { status: 503 },
        ),
      ),
    );
    renderApp();

    expect(await screen.findByText("Не удалось получить состояние сервисов")).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});
