import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { StepRemaining, StepSections } from "./StepSections";
import { useLeftSteps } from "./useLeftSteps";

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

/** Секция «Контакт»: галочка ставится валидатором, требования видны после ухода с шага, «Далее» не блокируется. */
function RequirementsHarness() {
  const [active, setActive] = useState("a");
  const [name, setName] = useState("");
  const { left } = useLeftSteps(active);
  const requirements = name.trim() ? [] : ["Укажите имя"];
  return (
    <StepSections
      active={active}
      onActiveChange={setActive}
      sections={[
        {
          key: "a",
          title: "Контакт",
          complete: true,
          requirements,
          showRequirements: left.has("a"),
          content: (
            <input
              aria-label="Имя"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          ),
        },
        { key: "b", title: "Запрос", content: <span>Суть</span> },
      ]}
    />
  );
}

describe("StepSections: требования шага (СЦ-6)", () => {
  it("на первом открытии требований нет; «Далее» не блокируется; покинутый неготовый шаг помечен и без галочки", () => {
    render(<RequirementsHarness />);
    expect(screen.queryByText("Укажите имя")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Далее: Запрос" }));
    expect(screen.getByText("Суть")).toBeVisible();
    const head = screen.getByRole("button", { name: /^Контакт/ });
    expect(head).toHaveTextContent("Нужно исправить");
    expect(head.querySelector(".lucide-check")).toBeNull();
    // вернулись на шаг: требование названо на самом шаге
    fireEvent.click(head);
    expect(screen.getByText("Чтобы шаг был готов:")).toBeVisible();
    expect(screen.getByText("Укажите имя")).toBeVisible();
  });

  it("галочка — только когда требований нет (тот же признак, что у отправки)", () => {
    render(<RequirementsHarness />);
    fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Азиз" } });
    fireEvent.click(screen.getByRole("button", { name: "Далее: Запрос" }));
    const head = screen.getByRole("button", { name: /^Контакт/ });
    expect(head).not.toHaveTextContent("Нужно исправить");
    expect(head.querySelector(".lucide-check")).not.toBeNull();
  });

  it("не покинутый шаг с невыполненным требованием не получает галочку и не пестрит требованиями", () => {
    render(
      <StepSections
        active="b"
        onActiveChange={() => undefined}
        sections={[
          {
            key: "a",
            title: "Контакт",
            complete: true,
            requirements: ["Укажите имя"],
            showRequirements: false,
            content: <span>Имя</span>,
          },
          { key: "b", title: "Запрос", content: <span>Суть</span> },
        ]}
      />,
    );
    const head = screen.getByRole("button", { name: /^Контакт/ });
    expect(head.querySelector(".lucide-check")).toBeNull();
    expect(head).not.toHaveTextContent("Нужно исправить");
  });

  it("«Осталось»: пункты ведут на шаг", () => {
    const go: string[] = [];
    render(
      <StepRemaining
        id="rest"
        items={[{ step: "a", title: "Контакт", text: "Укажите имя" }]}
        onGo={(step) => go.push(step)}
      />,
    );
    expect(screen.getByText("Осталось:")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Контакт" }));
    expect(go).toEqual(["a"]);
  });

  it("список «Осталось» пуст — компонента нет", () => {
    const { container } = render(<StepRemaining id="rest" items={[]} onGo={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
