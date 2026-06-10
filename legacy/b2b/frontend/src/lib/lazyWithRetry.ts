import { lazy, ComponentType } from 'react';

const RELOAD_FLAG = 'chunk-reload-attempted';

/**
 * React.lazy wrapper that recovers from stale-chunk failures after a deploy.
 *
 * When a new build ships, old hash-named chunks (e.g. AdminSupplierBidsPage-abc.js)
 * are removed from the server. A tab opened before the deploy still references the
 * old hashes, so the next lazy navigation throws "Failed to fetch dynamically
 * imported module" and the root ErrorBoundary shows a full white screen
 * (checkup 2026-06-09, ERR_UI_CRASH).
 *
 * On import failure we trigger ONE full reload to pull the fresh index.html + new
 * chunk hashes. A sessionStorage flag prevents an infinite reload loop if the
 * import is genuinely broken for another reason — in that case we rethrow and let
 * the ErrorBoundary handle it.
 */
export function lazyWithRetry<T extends ComponentType<unknown>>(importer: () => Promise<{ default: T }>) {
  return lazy(async () => {
    try {
      const component = await importer();
      // Clean load → clear the guard so a future stale chunk can reload again.
      window.sessionStorage.removeItem(RELOAD_FLAG);
      return component;
    } catch (error) {
      const alreadyReloaded = window.sessionStorage.getItem(RELOAD_FLAG);
      if (!alreadyReloaded) {
        window.sessionStorage.setItem(RELOAD_FLAG, '1');
        window.location.reload();
        // Keep Suspense on its fallback while the reload happens instead of
        // flashing the error boundary — this promise never resolves.
        return new Promise<{ default: T }>(() => {});
      }
      throw error;
    }
  });
}
