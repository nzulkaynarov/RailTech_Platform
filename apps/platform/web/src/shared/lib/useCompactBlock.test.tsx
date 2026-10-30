import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCompactBlock } from "./useCompactBlock";

type Callback = (entries: { contentRect: { width: number } }[]) => void;

let observed: Callback | undefined;

class ResizeObserverMock {
  constructor(callback: Callback) {
    observed = callback;
  }
  observe(): void {}
  disconnect(): void {}
}

function Probe({ fallback = false }: { fallback?: boolean }) {
  const { ref, compact } = useCompactBlock(700, fallback);
  return <div ref={ref}>{compact ? "список" : "таблица"}</div>;
}

function resize(width: number) {
  act(() => {
    observed?.([{ contentRect: { width } }]);
  });
}

describe("useCompactBlock", () => {
  const original = window.ResizeObserver;
  afterEach(() => {
    window.ResizeObserver = original;
    vi.restoreAllMocks();
    observed = undefined;
  });

  it("без замера — запасной вид", () => {
    render(<Probe fallback />);
    expect(screen.getByText("список")).toBeInTheDocument();
  });

  it("первый замер до отрисовки, обратно в таблицу — только с запасом 40 px", () => {
    window.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 800,
    } as DOMRect);
    render(<Probe fallback />);
    expect(screen.getByText("таблица")).toBeInTheDocument();

    resize(699);
    expect(screen.getByText("список")).toBeInTheDocument();
    // у самого порога вид не мигает
    resize(705);
    expect(screen.getByText("список")).toBeInTheDocument();
    resize(739);
    expect(screen.getByText("список")).toBeInTheDocument();
    resize(740);
    expect(screen.getByText("таблица")).toBeInTheDocument();
    resize(700);
    expect(screen.getByText("таблица")).toBeInTheDocument();
  });
});
