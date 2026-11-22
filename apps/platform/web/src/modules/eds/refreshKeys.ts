import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

/**
 * Query-key prefixes (orval keys) that one EDS action makes stale. Each action resets everything its result shows: the list
 * and card it came from, the documents it changes, «Моя очередь» and the menu counters, so a status never lags behind the
 * fact (СЦ-8). `refreshKeys.test.ts` pins every set.
 */
const QUEUE = ["/api/v1/queue", "/api/v1/menu-counters"] as const;

/** КП and memo approvals: the document registry and payment memos change with the decision too. */
export const APPROVAL_KEYS = [
  "/api/v1/eds/quotes",
  "/api/v1/eds/memo-approvals",
  "/api/v1/eds/documents",
  "/api/v1/eds/payment-memos",
  ...QUEUE,
] as const;

/** Letters: a reply (outgoing) is a document too. */
export const LETTER_KEYS = ["/api/v1/eds/letters", "/api/v1/eds/documents", ...QUEUE] as const;

/** Documents: signing a reply moves the incoming letter. */
export const DOCUMENT_KEYS = ["/api/v1/eds/documents", "/api/v1/eds/letters", ...QUEUE] as const;

/** ERP documents waiting for a signature: their own list, projects they belong to. */
export const SIGNING_KEYS = [
  "/api/v1/eds/signing-approvals",
  "/api/v1/eds/projects",
  ...QUEUE,
] as const;

/** Invalidates every query whose first key segment starts with one of `prefixes`. */
export function useInvalidatePrefixes(prefixes: readonly string[]): () => Promise<void> {
  const client = useQueryClient();
  return useCallback(
    () =>
      client.invalidateQueries({
        predicate: (query) => {
          const head = query.queryKey[0];
          return typeof head === "string" && prefixes.some((prefix) => head.startsWith(prefix));
        },
      }),
    [client, prefixes],
  );
}

export function useRefreshSigning(): () => Promise<void> {
  return useInvalidatePrefixes(SIGNING_KEYS);
}
