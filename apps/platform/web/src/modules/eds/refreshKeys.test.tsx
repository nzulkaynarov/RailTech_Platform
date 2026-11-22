import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { useRefreshApprovals } from "./decision/errors";
import { useRefreshDocuments } from "./documents/params";
import { useRefreshLetters } from "./inbox/api";
import { useRefreshSigning } from "./refreshKeys";

// СЦ-8: the action resets everything its result shows; the set of prefixes is the fact a status derives from.
const EVERY = [
  "/api/v1/eds/quotes",
  "/api/v1/eds/memo-approvals",
  "/api/v1/eds/documents",
  "/api/v1/eds/payment-memos",
  "/api/v1/eds/letters",
  "/api/v1/eds/signing-approvals",
  "/api/v1/eds/projects",
  "/api/v1/queue",
  "/api/v1/menu-counters",
  "/api/v1/unrelated",
] as const;

async function staleAfter(
  useHook: () => (() => unknown) | (() => Promise<void>),
): Promise<string[]> {
  const client = new QueryClient();
  // eslint-disable-next-line no-restricted-syntax -- the test pins the raw prefixes orval keys start with
  for (const key of EVERY) client.setQueryData([key], {});
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(useHook, { wrapper });
  await result.current();
  // eslint-disable-next-line no-restricted-syntax -- same raw prefixes
  return EVERY.filter((key) => client.getQueryState([key])?.isInvalidated);
}

const QUEUE = ["/api/v1/queue", "/api/v1/menu-counters"];

describe("сброс кэша после действия EDS", () => {
  it("решение по КП и служебке: КП, служебки, реестр, оплата, очередь и счётчики", async () => {
    expect(await staleAfter(useRefreshApprovals)).toEqual(
      expect.arrayContaining([
        "/api/v1/eds/quotes",
        "/api/v1/eds/memo-approvals",
        "/api/v1/eds/documents",
        "/api/v1/eds/payment-memos",
        ...QUEUE,
      ]),
    );
  });

  it("действие по письму: письма, документы (ответ), очередь и счётчики", async () => {
    expect(await staleAfter(useRefreshLetters)).toEqual(
      expect.arrayContaining(["/api/v1/eds/letters", "/api/v1/eds/documents", ...QUEUE]),
    );
  });

  it("действие по документу: документы, письма (входящее после подписи ответа), очередь и счётчики", async () => {
    expect(await staleAfter(useRefreshDocuments)).toEqual(
      expect.arrayContaining(["/api/v1/eds/documents", "/api/v1/eds/letters", ...QUEUE]),
    );
  });

  it("решение по подписи: свой список, проекты, очередь и счётчики", async () => {
    expect(await staleAfter(useRefreshSigning)).toEqual(
      expect.arrayContaining(["/api/v1/eds/signing-approvals", "/api/v1/eds/projects", ...QUEUE]),
    );
  });

  it("чужие запросы не трогаются", async () => {
    for (const hook of [
      useRefreshApprovals,
      useRefreshLetters,
      useRefreshDocuments,
      useRefreshSigning,
    ]) {
      expect(await staleAfter(hook)).not.toContain("/api/v1/unrelated");
    }
  });
});
