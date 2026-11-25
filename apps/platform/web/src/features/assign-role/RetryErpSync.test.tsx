import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { Employee } from "../../shared/api/generated/model";
import { ref } from "../../test/roles";
import { renderUi } from "../../test/renderUi";
import { server } from "../../test/server";
import { RetryErpSync } from "./RetryErpSync";

const employee: Employee = {
  id: "11",
  name: "Анна Демова",
  initials: "АД",
  email: "anna@demo.example",
  roles: [ref("MANAGER")],
  access: { crm: true, erp: true },
  status: "active",
  telegram_linked: false,
  telegram: "not_linked",
  erp_sync: "error",
};

describe("RetryErpSync", () => {
  it("«Повторить» вызывает маршрут повтора для этого сотрудника", async () => {
    const calls: string[] = [];
    server.use(
      http.post("*/admin/users/:id/erp-sync", ({ params }) => {
        calls.push(String(params["id"]));
        return HttpResponse.json({ ...employee, erp_sync: "pending" });
      }),
    );
    renderUi(<RetryErpSync employee={employee} />);

    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));

    await waitFor(() => {
      expect(calls).toEqual(["11"]);
    });
  });
});
