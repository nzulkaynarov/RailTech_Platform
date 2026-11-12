import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { StepSections } from "./StepSections";

import "../../i18n";

function Harness() {
  const [active, setActive] = useState("a");
  return (
    <StepSections
      active={active}
      onActiveChange={setActive}
      sections={[
        {
          key: "a",
          title: "О чём",
          summary: "ГНИ · gni@example.uz",
          complete: true,
          content: <input aria-label="Тема" />,
        },
        {
          key: "b",
          title: "Текст",
          summary: "Текста ещё нет",
          invalid: true,
          content: <textarea aria-label="Текст" />,
        },
        { key: "c", title: "Проверка", content: <button type="button">Отправить</button> },
      ]}
    />
  );
}

describe("StepSections (platform-frontend.md §4.1a)", () => {
  it("открыта одна секция; «Далее» сворачивает её в строку итога; к любой можно вернуться; ошибка помечена", () => {
    render(<Harness />);
    expect(screen.getByLabelText("Тема")).toBeVisible();
    expect(screen.getByLabelText("Текст")).not.toBeVisible();
    expect(screen.getByRole("button", { name: /Текст.*Нужно исправить/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    fireEvent.click(screen.getByRole("button", { name: "Далее: Текст" }));
    expect(screen.getByLabelText("Текст")).toBeVisible();
    expect(
      screen.getByRole("button", { name: /О чём.*ГНИ · gni@example\.uz.*Изменить/ }),
    ).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(screen.getByRole("button", { name: /^Проверка/ }));
    expect(screen.getByRole("button", { name: "Отправить" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Далее/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /О чём/ }));
    expect(screen.getByLabelText("Тема")).toBeVisible();
  });
});
