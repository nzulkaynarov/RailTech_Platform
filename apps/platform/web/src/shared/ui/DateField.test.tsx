import { fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderUi } from "../../test/renderUi";
import { DateField, DateRangeField } from "./DateField";

function openCalendar(input: HTMLElement) {
  fireEvent.mouseDown(input);
  fireEvent.focus(input);
  fireEvent.click(input);
}

function typeDate(input: HTMLElement, text: string) {
  fireEvent.mouseDown(input);
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
}

function Controlled(props: {
  initial?: string;
  min?: string;
  max?: string;
  onValue?: (v: string) => void;
}) {
  const [value, setValue] = useState(props.initial ?? "");
  return (
    <>
      <label htmlFor="due">Срок</label>
      <DateField
        id="due"
        value={value}
        min={props.min}
        max={props.max}
        aria-describedby="due-hint"
        onChange={(next) => {
          setValue(next);
          props.onValue?.(next);
        }}
      />
      <span id="due-hint">Подсказка</span>
      <output data-testid="value">{value}</output>
    </>
  );
}

describe("DateField", () => {
  it("показывает ДД.ММ.ГГГГ, подпись связана с полем, подсказка — через aria-describedby", () => {
    renderUi(<Controlled initial="2026-10-31" />);
    const input = screen.getByLabelText("Срок");
    expect(input).toHaveValue("31.10.2026");
    expect(input).toHaveAttribute("placeholder", "ДД.ММ.ГГГГ");
    expect(input).toHaveAttribute("aria-describedby", "due-hint");
  });

  it("ввод с клавиатуры: с точками и цифрами подряд, наружу — ключ YYYY-MM-DD", () => {
    const onValue = vi.fn();
    renderUi(<Controlled onValue={onValue} />);
    const input = screen.getByLabelText("Срок");
    typeDate(input, "05.11.2026");
    expect(onValue).toHaveBeenLastCalledWith("2026-11-05");
    expect(input).toHaveValue("05.11.2026");
    typeDate(input, "01122026");
    expect(onValue).toHaveBeenLastCalledWith("2026-12-01");
    expect(screen.getByTestId("value")).toHaveTextContent("2026-12-01");
  });

  it("очистка отдаёт пустую строку", () => {
    const onValue = vi.fn();
    const { container } = renderUi(<Controlled initial="2026-10-31" onValue={onValue} />);
    const clear = container.querySelector(".ant-picker-clear");
    expect(clear).not.toBeNull();
    fireEvent.mouseDown(clear as Element);
    fireEvent.mouseUp(clear as Element);
    fireEvent.click(clear as Element);
    expect(onValue).toHaveBeenLastCalledWith("");
  });

  it("min и max: дни вне диапазона в календаре отключены; набранную дату вне диапазона решает форма", () => {
    const onValue = vi.fn();
    renderUi(<Controlled min="2026-10-10" max="2026-10-20" onValue={onValue} />);
    const input = screen.getByLabelText("Срок");
    typeDate(input, "15.10.2026");
    expect(onValue).toHaveBeenLastCalledWith("2026-10-15");
    // как системное поле с min: набранное не стирается молча, а уходит форме — она пишет ошибку словами
    typeDate(input, "05.10.2026");
    expect(onValue).toHaveBeenLastCalledWith("2026-10-05");
    expect(input).toHaveValue("05.10.2026");
    typeDate(input, "15.10.2026");
    fireEvent.mouseDown(input);
    const cell = (day: string) =>
      document.querySelector<HTMLElement>(`.ant-picker-cell[title="${day}"]`);
    expect(cell("2026-10-09")).toHaveClass("ant-picker-cell-disabled");
    expect(cell("2026-10-21")).toHaveClass("ant-picker-cell-disabled");
    expect(cell("2026-10-12")).not.toHaveClass("ant-picker-cell-disabled");
  });

  it("aria-invalid формы доходит до поля", () => {
    renderUi(<DateField aria-label="Дата" value="" aria-invalid onChange={() => undefined} />);
    expect(screen.getByLabelText("Дата")).toHaveAttribute("aria-invalid", "true");
  });

  it("узбекский: латинские месяцы и подсказка формата", () => {
    renderUi(<Controlled initial="2026-10-31" />, { language: "uz" });
    const input = screen.getByLabelText("Срок");
    expect(input).toHaveAttribute("placeholder", "KK.OO.YYYY");
    expect(input).toHaveValue("31.10.2026");
    openCalendar(input);
    const month = document.querySelector(".ant-picker-month-btn");
    expect(month?.textContent).toMatch(/^[A-Za-z]/);
  });

  it("английский: тот же формат ДД.ММ.ГГГГ и английские месяцы", () => {
    renderUi(<Controlled initial="2026-10-31" />, { language: "en" });
    const input = screen.getByLabelText("Срок");
    expect(input).toHaveAttribute("placeholder", "DD.MM.YYYY");
    expect(input).toHaveValue("31.10.2026");
    openCalendar(input);
    expect(document.querySelector(".ant-picker-month-btn")?.textContent).toBe("Oct");
  });
});

describe("DateRangeField", () => {
  it("«с» не позже «по» и наоборот, подписи связаны с полями", () => {
    const onChange = vi.fn();
    renderUi(
      <div data-testid="range">
        <DateRangeField
          idFrom="from"
          idTo="to"
          labelFrom="С даты"
          labelTo="По дату"
          value={{ from: "2026-10-10", to: "2026-10-20" }}
          onChange={onChange}
        />
      </div>,
    );
    const range = screen.getByTestId("range");
    const from = within(range).getByLabelText("С даты");
    typeDate(from, "12.10.2026");
    expect(onChange).toHaveBeenLastCalledWith({ from: "2026-10-12", to: "2026-10-20" });
    const to = within(range).getByLabelText("По дату");
    fireEvent.mouseDown(to);
    fireEvent.click(to);
    // открыт календарь «по» — последний в документе
    const cell = (day: string) =>
      Array.from(document.querySelectorAll<HTMLElement>(`.ant-picker-cell[title="${day}"]`)).at(-1);
    expect(cell("2026-10-09")).toHaveClass("ant-picker-cell-disabled");
    expect(cell("2026-10-10")).not.toHaveClass("ant-picker-cell-disabled");
  });
});
