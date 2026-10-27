import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StaffAvatar } from "./StaffAvatar";

describe("StaffAvatar", () => {
  it("без фото — инициалы", () => {
    const { container } = render(<StaffAvatar initials="ДМ" />);
    expect(container).toHaveTextContent("ДМ");
    expect(container.querySelector("img")).toBeNull();
  });

  it("с фото — картинка вместо инициалов, декоративная", () => {
    const { container } = render(<StaffAvatar initials="ДМ" src="/api/v1/staff/7/avatar?v=1" />);
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "/api/v1/staff/7/avatar?v=1");
    expect(img).toHaveAttribute("alt", "");
    expect(container).not.toHaveTextContent("ДМ");
  });

  it("фото не загрузилось — возвращаются инициалы; новая версия адреса пробуется заново", () => {
    const { container, rerender } = render(<StaffAvatar initials="ДМ" src="/a?v=1" />);
    fireEvent.error(container.querySelector("img") as HTMLImageElement);
    expect(container).toHaveTextContent("ДМ");
    expect(container.querySelector("img")).toBeNull();

    rerender(<StaffAvatar initials="ДМ" src="/a?v=2" />);
    expect(container.querySelector("img")).toHaveAttribute("src", "/a?v=2");
  });
});
