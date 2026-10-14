import { setupServer } from 'msw/node';

import { handlers } from './handlers';

/** Тот же мок для Vitest: граница HTTP, компоненты не мокаются (CLAUDE.md §5). */
export const portalServer = setupServer(...handlers);
