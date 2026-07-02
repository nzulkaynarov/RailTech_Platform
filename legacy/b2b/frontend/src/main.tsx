import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';

import i18n from './i18n';
import { queryClient } from './lib/queryClient';
import { ErrorBoundary } from './components/Shared/ErrorBoundary';
import { initObservability } from './lib/observability';
import './index.css';
import App from './App';

initObservability();

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
