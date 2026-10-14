import { setupWorker } from 'msw/browser';

import { handlers } from './handlers';

/** Dev-мок портального API в браузере (только `import.meta.env.DEV` и `VITE_PORTAL_MOCK=1`, см. main.tsx). */
export async function startPortalMock(): Promise<void> {
  const worker = setupWorker(...handlers);
  await worker.start({ onUnhandledRequest: 'bypass', quiet: true });
}
