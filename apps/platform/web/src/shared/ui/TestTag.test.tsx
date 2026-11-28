import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import i18n from "../i18n";
import { TestTag } from "./TestTag";

beforeEach(() => {
  void i18n.changeLanguage("ru");
});

describe("TestTag", () => {
  it("рисует метку «Тестовая» только у записи тестовой компании", () => {
    const { rerender } = render(<TestTag value />);
    expect(screen.getByText("Тестовая")).toBeVisible();
    rerender(<TestTag value={false} />);
    expect(screen.queryByText("Тестовая")).toBeNull();
    rerender(<TestTag value={undefined} />);
    expect(screen.queryByText("Тестовая")).toBeNull();
  });

  it("говорит на языке интерфейса", async () => {
    await i18n.changeLanguage("uz");
    render(<TestTag value />);
    expect(screen.getByText("Sinov")).toBeVisible();
  });
});
