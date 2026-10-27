import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakeEventSource } from "../../test/fakeEventSource";
import { POLL_INTERVAL_MS, STREAM_POLL_INTERVAL_MS, pollInterval, usePollQuery } from "./polling";
import { isStreamLive } from "./streamState";
import { useEventStream } from "./useEventStream";

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function keysOf(spy: { mock: { calls: unknown[][] } }): string[] {
  return spy.mock.calls
    .map((call) => {
      const filters = call[0] as { queryKey?: string[]; predicate?: unknown };
      return filters.queryKey?.[0] ?? (filters.predicate ? "<predicate>" : "");
    })
    .sort();
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useEventStream", () => {
  it("подсказка перезапрашивает ровно запросы своих тем", () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    renderHook(
      () => {
        useEventStream(true);
      },
      { wrapper: wrapper(client) },
    );
    expect(FakeEventSource.last.init).toEqual({ withCredentials: true });
    act(() => {
      FakeEventSource.last.open();
    });

    act(() => {
      FakeEventSource.last.emit("invalidate", { topics: ["notifications"], reason: "r" });
    });
    expect(keysOf(spy)).toEqual(["/api/v1/notifications"]);

    spy.mockClear();
    act(() => {
      FakeEventSource.last.emit("invalidate", {
        topics: ["queue", "counters", "activity"],
        reason: "r",
      });
    });
    expect(keysOf(spy)).toEqual([
      "/api/v1/activity/today",
      "/api/v1/menu-counters",
      "/api/v1/queue",
      "/api/v1/queue/cards",
    ]);
  });

  it("после переподключения перезапрашивается всё", () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    renderHook(
      () => {
        useEventStream(true);
      },
      { wrapper: wrapper(client) },
    );
    act(() => {
      FakeEventSource.last.open();
      FakeEventSource.last.fail();
    });
    expect(spy).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1_300);
      FakeEventSource.last.open();
    });
    expect(keysOf(spy)).toEqual([
      "/api/v1/activity/today",
      "/api/v1/crm/messages",
      "/api/v1/menu-counters",
      "/api/v1/notifications",
      "/api/v1/queue",
      "/api/v1/queue/cards",
      "<predicate>",
    ]);
  });

  it("тема `messages` (D1-1): очередь «Ждут ответа» и открытая переписка лида, но не чужие запросы", () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    renderHook(
      () => {
        useEventStream(true);
      },
      { wrapper: wrapper(client) },
    );
    act(() => {
      FakeEventSource.last.open();
      FakeEventSource.last.emit("invalidate", {
        topics: ["counters", "queue", "messages"],
        reason: "uz.railtech.crm.lead.message_added.v1",
      });
    });
    expect(keysOf(spy)).toEqual([
      "/api/v1/crm/messages",
      "/api/v1/menu-counters",
      "/api/v1/queue",
      "/api/v1/queue/cards",
      "<predicate>",
    ]);
    const call = spy.mock.calls.find((c) => "predicate" in (c[0] ?? {}));
    const predicate = (
      call?.[0] as unknown as { predicate: (q: { queryKey: unknown[] }) => boolean }
    ).predicate;
    expect(predicate({ queryKey: ["/api/v1/crm/messages/L-2041/thread", { limit: 30 }] })).toBe(
      true,
    );
    expect(predicate({ queryKey: ["/api/v1/crm/messages/L-2041"] })).toBe(true);
    expect(predicate({ queryKey: ["/api/v1/crm/kb/documents"] })).toBe(false);
  });

  it("выключенный поток не открывается; закрывается при размонтировании", () => {
    const client = new QueryClient();
    const off = renderHook(
      () => {
        useEventStream(false);
      },
      { wrapper: wrapper(client) },
    );
    expect(FakeEventSource.instances).toHaveLength(0);
    off.unmount();

    const on = renderHook(
      () => {
        useEventStream(true);
      },
      { wrapper: wrapper(client) },
    );
    act(() => {
      FakeEventSource.last.open();
    });
    expect(isStreamLive()).toBe(true);
    on.unmount();
    expect(FakeEventSource.last.closed).toBe(true);
    expect(isStreamLive()).toBe(false);
  });

  it("без EventSource в браузере ничего не делает: остаётся опрос", () => {
    vi.stubGlobal("EventSource", undefined);
    const client = new QueryClient();
    renderHook(
      () => {
        useEventStream(true);
      },
      { wrapper: wrapper(client) },
    );
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(isStreamLive()).toBe(false);
  });
});

describe("опрос — запасной путь", () => {
  function Probe({ onInterval }: { onInterval: (ms: number) => void }) {
    onInterval(usePollQuery().refetchInterval);
    useEventStream(true);
    return null;
  }

  it("поток жив — опрос редкий, обрыв — опрос раз в 30 с, возврат потока — снова редкий", () => {
    const client = new QueryClient();
    const seen: number[] = [];
    render(
      <QueryClientProvider client={client}>
        <Probe onInterval={(ms) => seen.push(ms)} />
      </QueryClientProvider>,
    );
    expect(seen.at(-1)).toBe(POLL_INTERVAL_MS); // поток ещё не открыт

    act(() => {
      FakeEventSource.last.open();
    });
    expect(seen.at(-1)).toBe(STREAM_POLL_INTERVAL_MS);

    act(() => {
      FakeEventSource.last.fail();
    });
    expect(seen.at(-1)).toBe(POLL_INTERVAL_MS);

    act(() => {
      vi.advanceTimersByTime(1_300);
      FakeEventSource.last.open();
    });
    expect(seen.at(-1)).toBe(STREAM_POLL_INTERVAL_MS);
  });

  it("интервалы: 30 с без потока, 5 минут с потоком", () => {
    expect(pollInterval(false)).toBe(30_000);
    expect(pollInterval(true)).toBe(300_000);
  });
});
