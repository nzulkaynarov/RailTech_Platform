import { useState } from 'react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { RouterProvider, createBrowserRouter, type createMemoryRouter } from 'react-router-dom';

import { Toaster } from '@/components/ui/sonner';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { AppModeContext, type AppMode } from '@/session/mode';
import { isMiniApp } from '@/telegram/webapp';
import { createQueryClient } from './queryClient';
import { routes } from './routes';

type AppRouter = ReturnType<typeof createBrowserRouter> | ReturnType<typeof createMemoryRouter>;

/**
 * Корень: режим (Mini App / веб) определяется один раз, React Query — единственное хранилище
 * данных, маршрутизатор — react-router (тесты подставляют memory-router и свой QueryClient).
 */
export function App({ router, queryClient }: { router?: AppRouter; queryClient?: QueryClient }) {
  const [mode] = useState<AppMode>(() => (isMiniApp() ? 'miniapp' : 'web'));
  const [client] = useState(() => queryClient ?? createQueryClient());
  // От md слева боковая навигация, а заголовок страницы — вверху по центру: тост уходит вниз вправо, чтобы не закрывать h1.
  const sideNav = useMediaQuery('(min-width: 768px)');
  const [appRouter] = useState(() => router ?? createBrowserRouter(routes));

  return (
    <AppModeContext.Provider value={mode}>
      <QueryClientProvider client={client}>
        <RouterProvider router={appRouter} />
        <Toaster position={sideNav ? 'bottom-right' : 'top-center'} visibleToasts={3} />
      </QueryClientProvider>
    </AppModeContext.Provider>
  );
}
