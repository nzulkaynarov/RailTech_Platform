import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { RequestSteps } from "./RequestSteps";

describe("RequestSteps", () => {
  it("семь шагов по SPEC-v3 §2.3 в списке с именем", () => {
    renderUi(<RequestSteps stage="QUOTE" number="ЗВ-2026-104" />);
    const list = screen.getByRole("list", { name: "Путь заявки ЗВ-2026-104" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((li) => li.querySelector(".pf-step-label")?.firstChild?.textContent)).toEqual([
      "Заявка",
      "Резолюция",
      "Расчёт",
      "КП",
      "Договор",
      "Оплата",
      "Выполнено",
    ]);
  });

  it("текущий шаг — aria-current, пройденные и будущие названы словами, не только цветом", () => {
    renderUi(<RequestSteps stage="CALCULATION" />);
    const items = screen.getAllByRole("listitem");
    expect(items[2]).toHaveAttribute("aria-current", "step");
    expect(items.filter((li) => li.hasAttribute("aria-current"))).toHaveLength(1);
    expect(items[0]).toHaveTextContent("Заявка, пройден");
    expect(items[2]).toHaveTextContent("Расчёт, текущий шаг");
    expect(items[3]).toHaveTextContent("КП, впереди");
    expect(items[0]).toHaveClass("pf-step--done");
    expect(items[2]).toHaveClass("pf-step--current");
    expect(items[3]).toHaveClass("pf-step--upcoming");
  });

  it("пройденный шаг — галочка вместо номера, остальные — номер", () => {
    renderUi(<RequestSteps stage="CONTRACT" />);
    const nums = document.querySelectorAll(".pf-step-num");
    expect(nums[0]?.querySelector("svg")).not.toBeNull();
    expect(nums[4]).toHaveTextContent("5");
    expect(nums[6]).toHaveTextContent("7");
  });

  it("«Выполнено» — все шаги пройдены, текущего нет", () => {
    renderUi(<RequestSteps stage="DONE" />);
    expect(document.querySelectorAll(".pf-step--done")).toHaveLength(7);
    expect(document.querySelector("[aria-current]")).toBeNull();
  });

  it("«Отказ» — тег рядом со шкалой; шаги до отказа остаются пройденными", () => {
    renderUi(<RequestSteps stage="LOST" step={4} number="ЗВ-2026-097" />);
    expect(screen.getByText("Отказ", { selector: ".ant-tag" })).toBeVisible();
    expect(screen.getByText("(остановлена на шаге 4)")).toBeInTheDocument();
    expect(document.querySelectorAll(".pf-step--done")).toHaveLength(3);
    expect(document.querySelector("[aria-current]")).toBeNull();
  });

  it("подписи по языку интерфейса", () => {
    renderUi(<RequestSteps stage="REQUEST" />, { language: "en" });
    expect(screen.getByRole("list", { name: "Request path" })).toBeInTheDocument();
    expect(screen.getByText("Costing", { exact: false })).toBeInTheDocument();
  });
});
