import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { countLabel, stripCount, titleWithCount, useTaskCountTitle } from "./useTaskCountTitle";

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

  it("пустой заголовок: число без хвостового пробела и без накопления (иначе наблюдатель дописывает префикс бесконечно)", async () => {
    document.head.innerHTML = "<title></title>";
    renderHook(() => {
      useTaskCountTitle(5);
    });
    await settle();
    await settle();
    expect(document.title).toBe("(5)");
    // страница позже задала заголовок — число встаёт перед ним один раз
    document.title = "Telegram — RailTech";
    await settle();
    expect(document.title).toBe("(5) Telegram — RailTech");
    expect(titleWithCount("(5)", 7)).toBe("(7)");
    expect(titleWithCount("  ", 0)).toBe("");
  });

  it("два вызова с разными числами не переписывают заголовок друг за другом: действует последнее число", async () => {
    const first = renderHook(() => {
      useTaskCountTitle(0);
    });
    renderHook(() => {
      useTaskCountTitle(10);
    });
    await settle();
    await settle();
    expect(document.title).toBe("(10) Задачи — RailTech");
    document.title = "Telegram — RailTech";
    await settle();
    await settle();
    expect(document.title).toBe("(10) Telegram — RailTech");
    // один из двух ушёл — число остаётся, пока жив второй
    first.unmount();
    await settle();
    expect(document.title).toBe("(10) Telegram — RailTech");
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
