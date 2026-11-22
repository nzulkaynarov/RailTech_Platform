import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { countLabel, stripCount, useTaskCountTitle } from "./useTaskCountTitle";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("useTaskCountTitle", () => {
  beforeEach(() => {
    document.head.innerHTML = "<title>Задачи — RailTech</title>";
  });
  afterEach(() => {
    document.head.innerHTML = "";
  });

  it("ставит число задач перед заголовком вкладки", () => {
    renderHook(() => {
      useTaskCountTitle(5);
    });
    expect(document.title).toBe("(5) Задачи — RailTech");
  });

  it("нуль — без числа, число меняется на месте без накопления", () => {
    const { rerender } = renderHook(
      ({ count }: { count: number }) => {
        useTaskCountTitle(count);
      },
      { initialProps: { count: 5 } },
    );
    rerender({ count: 7 });
    expect(document.title).toBe("(7) Задачи — RailTech");
    rerender({ count: 0 });
    expect(document.title).toBe("Задачи — RailTech");
  });

  it("страница сменила заголовок — число остаётся", async () => {
    renderHook(() => {
      useTaskCountTitle(3);
    });
    document.title = "Клиенты — RailTech";
    await settle();
    expect(document.title).toBe("(3) Клиенты — RailTech");
  });

  it("после размонтирования заголовок чистый", () => {
    const { unmount } = renderHook(() => {
      useTaskCountTitle(4);
    });
    unmount();
    expect(document.title).toBe("Задачи — RailTech");
  });

  it("больше 99 — «99+»", () => {
    expect(countLabel(240)).toBe("99+");
    expect(countLabel(99)).toBe("99");
    expect(stripCount("(99+) Задачи")).toBe("Задачи");
  });
});
