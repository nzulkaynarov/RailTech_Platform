import { afterEach, describe, expect, it, vi } from "vitest";

import { consume, keysFor, parseSse } from "./useEventStream";

describe("parseSse", () => {
  it("splits complete events and keeps the tail", () => {
    const input =
      'retry: 3000\n\nevent: lead.updated\ndata: {"type":"lead.updated","lead_id":5}\n\n: keepalive\n\nevent: mess';
    const { events, rest } = parseSse(input);
    expect(events).toEqual([{ type: "lead.updated", lead_id: 5 }]);
    expect(rest).toBe("event: mess");
  });

  it("skips broken payloads", () => {
    expect(parseSse("data: {oops\n\n").events).toEqual([]);
  });
});

describe("keysFor", () => {
  it("invalidates the lead and lists", () => {
    expect(keysFor({ type: "message.created", lead_id: 7 })).toEqual([
      ["inbox"],
      ["leads"],
      ["lead", 7],
    ]);
  });
});

describe("consume", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not report the stream as open when the server refuses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    const onOpen = vi.fn();
    await expect(consume(new AbortController().signal, vi.fn(), onOpen)).rejects.toThrow();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("reports open after a successful response and delivers events", async () => {
    const body = 'data: {"type":"lead.updated","lead_id":3}\n\n';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    const onOpen = vi.fn();
    const onEvent = vi.fn();
    await consume(new AbortController().signal, onEvent, onOpen);
    expect(onOpen).toHaveBeenCalledOnce();
    expect(onEvent.mock.calls[0]?.[0]).toEqual({ type: "lead.updated", lead_id: 3 });
  });
});
