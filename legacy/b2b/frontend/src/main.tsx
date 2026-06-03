import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider, MutationCache } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import { toast } from 'sonner';

import i18n from './i18n';
import { translateApiError } from './lib/apiError';
import { ErrorBoundary } from './components/Shared/ErrorBoundary';
import { initObservability } from './lib/observability';
import './index.css';
import App from './App';

initObservability();

const queryClient = new QueryClient({
  // Single source of truth for mutation errors: any mutation that does not opt out
  // surfaces a localised toast. Prevents the "action silently failed" class of bugs.
  // A mutation can opt out with meta: { skipErrorToast: true } when it shows its own UI.
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (mutation.meta?.skipErrorToast) return;
      toast.error(translateApiError(error));
    },
  }),
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // Don't retry 4xx client errors (auth, not-found, etc) — they won't succeed
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 1;
      },
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      refetchOnMount: false,
      staleTime: 2 * 60_000,
      gcTime: 10 * 60_000,
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        {/* Root-level boundary: a render crash anywhere shows the recovery UI
            instead of a white screen. Inner boundaries can still scope errors. */}
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </QueryClientProvider>
    </I18nextProvider>
  </StrictMode>,
);
