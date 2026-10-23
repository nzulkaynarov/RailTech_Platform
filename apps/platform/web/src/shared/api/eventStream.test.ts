import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakeEventSource } from "../../test/fakeEventSource";
import { BACKOFF_MS, EventStreamClient, parseHint, type EventStreamOptions } from "./eventStream";

function setup(extra: Partial<EventStreamOptions> = {}) {
  const calls = {
    hints: [] as [string[], string][],
    resync: 0,
    live: [] as boolean[],
  };
  const client = new EventStreamClient({
    createSource: (url) => new FakeEventSource(url),
    random: () => 0.5, // разброс 0,8…1,2 → ровно ×1
    onHint: (topics, reason) => calls.hints.push([topics, reason]),
    onResync: () => {
      calls.resync += 1;
    },
    onLive: (live) => calls.live.push(live),
    ...extra,
  });
  return { client, calls };
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.reset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("parseHint", () => {
  it("берёт известные темы и причину", () => {
    expect(
      parseHint('{"topics":["queue","bogus","counters"],"reason":"uz.railtech.erp.x.v1"}'),
    ).toEqual({
      topics: ["queue", "counters"],
      reason: "uz.railtech.erp.x.v1",
    });
  });
  it.each([
    "",
    "not json",
    "null",
    "[]",
    '{"topics":"queue"}',
    '{"topics":["bogus"],"reason":"x"}',
  ])("мусор %j отбрасывается", (raw) => {
    expect(parseHint(raw)).toBeNull();
  });
});

describe("EventStreamClient", () => {
  it("открывается по адресу потока, поток живой после open, подсказка доходит до приложения", () => {
    const { client, calls } = setup();
    client.start();
    const source = FakeEventSource.last;
    expect(source.url).toBe("/api/v1/events/stream");
    expect(calls.live).toEqual([]);

    source.open();
    expect(calls.live).toEqual([true]);
    expect(calls.resync).toBe(0); // первое открытие — не переподключение

    source.emit("invalidate", { topics: ["notifications", "counters"], reason: "r" });
    expect(calls.hints).toEqual([[["notifications", "counters"], "r"]]);

    source.emit("invalidate", "мусор");
    expect(calls.hints).toHaveLength(1);
  });

  it("обрыв: поток закрыт, опрос включается, переподключение с нарастающей задержкой", () => {
    const { client, calls } = setup();
    client.start();
    FakeEventSource.last.open();

    FakeEventSource.last.fail();
    expect(calls.live).toEqual([true, false]);
    expect(FakeEventSource.last.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(1);

    // каждый следующий обрыв без открытия ждёт дольше: 1, 2, 4, 8, 16, 30, 30 с
    for (const delay of [...BACKOFF_MS, BACKOFF_MS.at(-1)]) {
      vi.advanceTimersByTime((delay ?? 0) - 1);
      const before = FakeEventSource.instances.length;
      expect(FakeEventSource.instances).toHaveLength(before);
      vi.advanceTimersByTime(1);
      expect(FakeEventSource.instances).toHaveLength(before + 1);
      FakeEventSource.last.fail();
    }
  });

  it("после переподключения — один полный перезапрос и задержка начинается заново", () => {
    const { client, calls } = setup();
    client.start();
    FakeEventSource.last.open();
    FakeEventSource.last.fail();
    vi.advanceTimersByTime(1_000);
    FakeEventSource.last.fail();
    vi.advanceTimersByTime(2_000);
    FakeEventSource.last.open();
    expect(calls.resync).toBe(1);
    expect(calls.live).toEqual([true, false, false, true]);

    FakeEventSource.last.fail();
    const count = FakeEventSource.instances.length;
    vi.advanceTimersByTime(1_000); // снова с первой ступени
    expect(FakeEventSource.instances).toHaveLength(count + 1);
  });

  it("первое открытие после неудачных попыток — тоже не переподключение", () => {
    const { client, calls } = setup();
    client.start();
    FakeEventSource.last.fail(); // сервер ещё не отвечал
    vi.advanceTimersByTime(1_000);
    FakeEventSource.last.open();
    expect(calls.resync).toBe(0);
    expect(calls.live).toEqual([false, true]);
  });

  it("stop закрывает поток, отменяет переподключение и гасит «живой»", () => {
    const { client, calls } = setup();
    client.start();
    FakeEventSource.last.open();
    client.stop();
    expect(FakeEventSource.last.closed).toBe(true);
    expect(calls.live).toEqual([true, false]);

    const { client: other } = setup();
    other.start();
    FakeEventSource.last.fail();
    other.stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeEventSource.instances).toHaveLength(2); // новых соединений нет
  });

  it("события закрытого соединения игнорируются", () => {
    const { client, calls } = setup();
    client.start();
    const old = FakeEventSource.last;
    old.open();
    old.fail();
    old.emit("invalidate", { topics: ["queue"], reason: "late" });
    old.open();
    expect(calls.hints).toEqual([]);
    expect(calls.live).toEqual([true, false]);
  });

  it("разброс задержки ±20 %", () => {
    const { client } = setup({ random: () => 0 });
    client.start();
    FakeEventSource.last.fail();
    vi.advanceTimersByTime(799);
    expect(FakeEventSource.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeEventSource.instances).toHaveLength(2);
  });
});
