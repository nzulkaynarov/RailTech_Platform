import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { StatusFact, StatusState } from "../api/generated/model";
import { renderUi } from "../../test/renderUi";
import { StatusStrip } from "./StatusStrip";

const NOW = new Date("2026-11-27T10:00:00Z");
const fact = (
  state: StatusState,
  checkedAt: string | null = "2026-11-27T09:57:00Z",
): StatusFact => ({
  state,
  checked_at: checkedAt,
  source: "check",
  live: state === "works",
});

describe("StatusStrip — полоса статуса (НАСТ-П1)", () => {
  it.each([
    ["works", "Работает"],
    ["attention", "Внимание"],
    ["broken", "Сбой"],
    ["not_verified", "Настроено, не проверено"],
    ["stale", "Нет свежих данных"],
    ["unknown", "Не удалось проверить"],
    ["off", "Не подключено"],
  ] as const)("слово состояния %s — «%s»", (state, word) => {
    renderUi(<StatusStrip fact={fact(state)} scope="связь с расчётами" now={NOW} />);
    expect(screen.getByText(word)).toBeVisible();
  });

  it("подпись называет, что проверено, и когда; кнопка «Проверить» — только с обработчиком", () => {
    const onCheck = vi.fn();
    renderUi(
      <StatusStrip
        fact={fact("works")}
        scope="связь с расчётами"
        now={NOW}
        onCheck={onCheck}
        checkAria="Проверить: ERP"
      />,
    );
    expect(screen.getByText(/связь с расчётами · проверено 3 минуты назад/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Проверить: ERP" }));
    expect(onCheck).toHaveBeenCalledTimes(1);
  });

  it("без обработчика кнопки нет; проверки не было — «проверки ещё не было», а не дата", () => {
    renderUi(<StatusStrip fact={fact("not_verified", null)} scope="отправка и приём писем" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/проверки ещё не было/)).toBeVisible();
  });

  it("слово без времени проверки и источника не компилируется (тип)", () => {
    // @ts-expect-error — у модели статуса обязательны `checked_at` и `source`: голое слово «Работает» нельзя
    const bare: StatusFact = { state: "works", live: true };
    // @ts-expect-error — и `fact` целиком обязателен: строка вместо модели не принимается
    const literal = <StatusStrip fact="works" scope="x" />;
    expect(bare).toBeDefined();
    expect(literal).toBeDefined();
  });

  it("цвет «Работает» — зелёный только у works; «не проверено» и «не удалось» — нейтральные", () => {
    const { rerender } = renderUi(<StatusStrip fact={fact("works")} scope="x" now={NOW} />);
    expect(screen.getByText("Работает").closest(".ant-tag")).toHaveAttribute("data-tone", "green");
    rerender(<StatusStrip fact={fact("not_verified", null)} scope="x" now={NOW} />);
    expect(screen.getByText("Настроено, не проверено").closest(".ant-tag")).not.toHaveAttribute(
      "data-tone",
      "green",
    );
  });
});
