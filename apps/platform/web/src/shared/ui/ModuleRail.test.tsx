import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { ModuleRail, type RailModule } from "./ModuleRail";

function rail(variant: "side" | "bottom", badge?: RailModule["badge"]) {
  const modules: RailModule[] = [
    {
      code: "dashboard",
      name: "Главная",
      to: "/dashboard/queue",
      active: true,
      ...(badge ? { badge } : {}),
    },
    { code: "crm", name: "Клиенты", to: "/crm/leads", active: false },
  ];
  renderUi(
    <ModuleRail
      modules={modules}
      variant={variant}
      label="Модули"
      logoLabel="RT"
      logoText="RT"
      logoTo="/"
      profile={<span />}
    />,
  );
}

describe.each(["side", "bottom"] as const)(
  "ModuleRail (%s): число задач на «Главной»",
  (variant) => {
    it("значок с числом, имя ссылки называет задачи", () => {
      rail(variant, { count: 5, label: "Главная, задач: 5" });
      expect(screen.getByRole("link", { name: "Главная, задач: 5" })).toBeVisible();
      expect(screen.getByTestId("rail-count-dashboard")).toHaveAttribute("data-count", "5");
      // у модуля без числа значка нет
      expect(screen.getByRole("link", { name: "Клиенты" })).toBeVisible();
      expect(screen.queryByTestId("rail-count-crm")).toBeNull();
    });

    it("нуль задач — без значка и без чужого имени", () => {
      rail(variant);
      expect(screen.getByRole("link", { name: "Главная" })).toBeVisible();
      expect(screen.queryByTestId("rail-count-dashboard")).toBeNull();
    });

    it("больше 99 — «99+»", () => {
      rail(variant, { count: 240, label: "Главная, задач: 240" });
      expect(screen.getByTestId("rail-count-dashboard")).toHaveAttribute("data-count", "99+");
    });
  },
);
