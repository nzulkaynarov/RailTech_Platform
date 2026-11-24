import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useCrumbTitle, useCrumbTitleValue } from "./crumbTitle";

afterEach(cleanup);

describe("useCrumbTitle: последняя крошка называет объект", () => {
  it("номер счёта, а не «142» из адреса; после ухода с карточки название снимается", () => {
    const shell = renderHook(() => useCrumbTitleValue());
    expect(shell.result.current).toBeNull();

    const card = renderHook(
      ({ title }) => {
        useCrumbTitle(title);
      },
      {
        initialProps: { title: undefined as string | undefined },
      },
    );
    // карточка ещё грузится: названия нет, в крошке остаётся идентификатор из адреса
    expect(shell.result.current).toBeNull();

    card.rerender({ title: "INV-2026-142" });
    expect(shell.result.current).toBe("INV-2026-142");

    card.unmount();
    expect(shell.result.current).toBeNull();
  });
});
