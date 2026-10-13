import type { ReactElement, ReactNode } from 'react';
import { render, type RenderOptions, type RenderResult } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createInstance, type i18n as I18nInstance } from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';

import ru from '@/i18n/locales/ru.json';

/**
 * Fresh i18next instance loaded with the REAL ru.json locale (no LanguageDetector,
 * so the language is deterministic in jsdom). Asserting on the resolved Russian
 * strings — instead of raw keys — catches missing-key bugs (i18next renders the
 * key itself when a translation is absent, which makes such assertions fail).
 */
export function createTestI18n(): I18nInstance {
  const instance = createInstance();
  instance.use(initReactI18next).init({
    lng: 'ru',
    fallbackLng: 'ru',
    resources: { ru: { translation: ru } },
    interpolation: { escapeValue: false },
    // Init synchronously — resources are inline, no backend to wait for.
    initImmediate: false,
  });
  return instance;
}

/** React Query client tuned for tests: no retries, no background refetch noise. */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}

interface ProviderRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  queryClient?: QueryClient;
}

interface ProviderRenderResult extends RenderResult {
  queryClient: QueryClient;
}

/**
 * Shared render helper for component tests: wraps the UI in QueryClientProvider
 * (fresh client, retry off) + I18nextProvider (real ru.json). Mock the API layer
 * (`vi.mock('@/api/...')`) in the test file — never intercept network requests.
 */
export function renderWithProviders(
  ui: ReactElement,
  { queryClient = createTestQueryClient(), ...renderOptions }: ProviderRenderOptions = {},
): ProviderRenderResult {
  const i18n = createTestI18n();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
      </QueryClientProvider>
    );
  }

  return { ...render(ui, { wrapper: Wrapper, ...renderOptions }), queryClient };
}
