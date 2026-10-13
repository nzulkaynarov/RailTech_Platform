import { describe, expect, it } from "vitest";

import { documentTitle } from "./documentTitle";

describe("documentTitle", () => {
  it.each([
    [
      {
        resource: { name: "inbox", meta: { label: "Входящие" } },
        action: "list",
        pathname: "/inbox",
      },
      "Входящие — RailTech CRM",
    ],
    [
      {
        resource: { name: "leads", meta: { label: "Лиды" } },
        action: "show",
        params: { id: "11" },
        pathname: "/leads/11",
      },
      "Лид #11 — RailTech CRM",
    ],
    [
      {
        resource: { name: "clients", meta: { label: "Клиенты" } },
        action: "show",
        params: { id: "4" },
        pathname: "/clients/4",
      },
      "Клиент #4 — RailTech CRM",
    ],
    [{ pathname: "/login" }, "Вход — RailTech CRM"],
    [{ pathname: "/change-password" }, "Смена пароля — RailTech CRM"],
    [{ pathname: "/nope" }, "Страница не найдена — RailTech CRM"],
    [{ pathname: "/" }, "RailTech CRM"],
  ])("%j → %s", (options, expected) => {
    expect(documentTitle(options)).toBe(expected);
  });
});
