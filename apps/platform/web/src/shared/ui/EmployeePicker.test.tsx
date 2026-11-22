import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EmployeePicker } from "./EmployeePicker";

const OPTIONS = [
  { id: "3", name: "Рустам Директоров", position: "Директор" },
  { id: "4", name: "Регина Регистраторова", position: "Делопроизводитель" },
];

describe("EmployeePicker", () => {
  it("ищет по имени и должности и отдаёт выбранную строку", () => {
    const onChange = vi.fn();
    render(<EmployeePicker id="p" value={undefined} options={OPTIONS} onChange={onChange} />);
    const box = screen.getByRole("combobox");
    fireEvent.mouseDown(box);
    fireEvent.change(box, { target: { value: "делопр" } });
    expect(screen.queryByTitle("Рустам Директоров")).toBeNull();
    fireEvent.click(screen.getByTitle("Регина Регистраторова"));
    expect(onChange).toHaveBeenCalledWith("4", OPTIONS[1]);
  });

  it("в пустом списке говорит словами", () => {
    render(
      <EmployeePicker
        id="p"
        value={undefined}
        options={[]}
        onChange={vi.fn()}
        emptyText="Никого"
      />,
    );
    fireEvent.mouseDown(screen.getByRole("combobox"));
    expect(screen.getByText("Никого")).toBeInTheDocument();
  });
});
