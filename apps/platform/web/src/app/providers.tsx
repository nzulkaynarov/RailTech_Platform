import { type QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import type { Locale } from "antd/es/locale";
import enUS from "antd/es/locale/en_US";
import ruRU from "antd/es/locale/ru_RU";
import uzUZ from "antd/es/locale/uz_UZ";
import { type ReactNode, useEffect, useRef } from "react";
import { I18nextProvider, useTranslation } from "react-i18next";

import i18n from "../shared/i18n";
import { createQueryClient } from "./queryClient";
import { appTheme } from "./theme";

const ANTD_LOCALES: Record<string, Locale> = { ru: ruRU, uz: uzUZ, en: enUS };

/**
 * Строки «Главной» BFF собирает на языке запроса (`Accept-Language`): при смене языка очередь и карточки перечитываются,
 * иначе до следующего опроса остался бы текст прежнего языка (СЦ-7, N1).
 */
function useRefetchQueueOnLanguage(language: string) {
  const client = useQueryClient();
  const previous = useRef(language);
  useEffect(() => {
    if (previous.current === language) return;
    previous.current = language;
    void client.invalidateQueries({
      predicate: (query) => /^\/api\/v1\/(queue|activity)/.test(String(query.queryKey[0])),
    });
  }, [client, language]);
}

function ThemedApp({ children }: { children: ReactNode }) {
  const { i18n: instance } = useTranslation();
  useRefetchQueueOnLanguage(instance.language);
  const locale = ANTD_LOCALES[instance.language] ?? ruRU;
  return (
    <ConfigProvider theme={appTheme} locale={locale}>
      <AntApp>{children}</AntApp>
    </ConfigProvider>
  );
}

/** Query → i18n → ConfigProvider (тема и локаль antd). Роутер подключает `App`. */
export function AppProviders({
  children,
  queryClient,
}: {
  children: ReactNode;
  queryClient?: QueryClient;
}) {
  return (
    <QueryClientProvider client={queryClient ?? createQueryClient()}>
      <I18nextProvider i18n={i18n}>
        <ThemedApp>{children}</ThemedApp>
      </I18nextProvider>
    </QueryClientProvider>
  );
}
