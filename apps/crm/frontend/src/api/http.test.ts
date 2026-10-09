import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, http, refreshAccess, tokenStore } from "./http";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("http", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    tokenStore.set(null);
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    tokenStore.set("old");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { code: "auth_failed" }))
      .mockResolvedValueOnce(json(200, { access_token: "new" }))
      .mockResolvedValueOnce(json(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await http<{ data: unknown; status: number }>("/api/v1/leads", {});
    expect(result.status).toBe(200);
    const retried = fetchMock.mock.calls[2]?.[1] as RequestInit;
    expect(new Headers(retried.headers).get("Authorization")).toBe("Bearer new");
  });

  it("maps domain errors to ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json(409, { code: "last_admin", message: "x" })),
    );
    await expect(http("/api/v1/users/1", {})).rejects.toMatchObject({
      status: 409,
      code: "last_admin",
    } satisfies Partial<ApiError>);
  });

  it("does not wipe a token obtained while a failed refresh was in flight", async () => {
    let finish: (value: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
      ),
    );
    const pending = refreshAccess();
    tokenStore.set("fresh-login");
    finish(json(401, { code: "auth_failed" }));
    expect(await pending).toBe(true);
    expect(tokenStore.get()).toBe("fresh-login");
  });
});

describe("compact", () => {
  it("drops empty filters so they are not sent as the string 'null'", async () => {
    const { compact } = await import("./http");
    expect(compact({ q: null, stage: "won", owner: undefined, language: "" })).toEqual({
      stage: "won",
    });
  });
});
