import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getGetLeadQueryKey,
  getInboxQueryKey,
  getLeadDecisionsQueryKey,
  getLeadMessagesQueryKey,
  getLeadNotesQueryKey,
  getListClientsQueryKey,
  getListLeadsQueryKey,
  getListServiceRequestsQueryKey,
} from "../api/generated/crm";
import { type CrmEvent, consume, keysFor, parseSse } from "./useEventStream";

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

const LISTS = [getInboxQueryKey(), getListServiceRequestsQueryKey(), getListLeadsQueryKey()];
const LEAD_7 = [
  getGetLeadQueryKey(7),
  getLeadMessagesQueryKey(7),
  getLeadNotesQueryKey(7),
  getLeadDecisionsQueryKey(7),
];

describe("keysFor", () => {
  it.each<[CrmEvent["type"], number | null, unknown[]]>([
    ["message.created", 7, [...LISTS, ...LEAD_7]],
    ["lead.updated", 7, [...LISTS, ...LEAD_7]],
    ["escalation.updated", 7, [...LISTS, ...LEAD_7]],
    ["message.created", null, LISTS],
    ["lead.updated", null, LISTS],
    ["escalation.updated", null, LISTS],
  ])("%s (lead %s) invalidates the expected generated keys", (type, leadId, expected) => {
    expect(keysFor({ type, lead_id: leadId })).toEqual(expected);
  });

  it("treats an event without lead_id as a list-only change", () => {
    expect(keysFor({ type: "lead.updated" })).toEqual(LISTS);
  });

  it("hits cached queries of the lead and every list page, not other leads or clients", async () => {
    const client = new QueryClient();
    const cached = [
      getListLeadsQueryKey({ limit: 50, offset: 100, stage: "qualified" }),
      getListServiceRequestsQueryKey({ status: "open" }),
      getInboxQueryKey(),
      getGetLeadQueryKey(7),
      getLeadMessagesQueryKey(7),
      getGetLeadQueryKey(8),
      getLeadMessagesQueryKey(8),
      getListClientsQueryKey(),
    ];
    for (const key of cached) client.setQueryData(key, {});
    for (const queryKey of keysFor({ type: "message.created", lead_id: 7 }))
      await client.invalidateQueries({ queryKey });
    const stale = client
      .getQueryCache()
      .findAll()
      .filter((q) => q.state.isInvalidated)
      .map((q) => q.queryKey);
    expect(stale).toEqual(cached.slice(0, 5));
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
