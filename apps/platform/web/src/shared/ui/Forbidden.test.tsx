import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { server } from "../../test/server";
import { Forbidden } from "./Forbidden";

describe("Forbidden", () => {
  it("заголовок страницы, пояснение и рабочая кнопка «Написать администратору» (W15-H7)", () => {
    renderUi(<Forbidden />);
    expect(screen.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(
      screen.getByRole("heading", { level: 2, name: "Этот раздел недоступен для вашей роли" }),
    ).toBeVisible();
    const button = screen.getByRole("button", { name: /Написать администратору/ });
    expect(button).toBeEnabled();
    expect(document.title).toBe("Нет доступа — Платформа"); // название не задано — нейтральное (задача «Н3»)
  });

  it("«Раздел доступен ролям: …»", () => {
    renderUi(<Forbidden roles={["Директор", "Бухгалтер"]} />);
    expect(screen.getByText(/Раздел доступен ролям: Директор, Бухгалтер\./)).toBeVisible();
  });

  it("встроенный: без h1 и без смены заголовка вкладки", () => {
    document.title = "Витрина";
    renderUi(<Forbidden embedded />);
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.getByRole("heading", { level: 3 })).toBeVisible();
    expect(document.title).toBe("Витрина");
  });

  it("уровень «смотреть» по возможности, которой нужно «работать»: называет уровень, а не «нет совсем»", async () => {
    server.use(
      http.get("*/me/capabilities", () =>
        HttpResponse.json({
          groups: [
            {
              key: "g",
              rows: [
                {
                  key: "admin",
                  name: { ru: "Сотрудники и возможности", uz: "", en: "" },
                  level: "view",
                  levels: [
                    { level: "work", actions: [{ key: "edit", gates: ["admin:full"], on: false }] },
                  ],
                },
              ],
            },
          ],
          grantors: [],
        }),
      ),
    );
    renderUi(<Forbidden rule={{ resource: "admin", level: "full" }} />);
    expect(
      await screen.findByText(
        /Возможность «Сотрудники и возможности» у вас есть, но только чтобы смотреть; здесь нужно работать\./,
      ),
    ).toBeVisible();
  });
});
