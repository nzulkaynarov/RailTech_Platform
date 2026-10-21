import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import type { Locale } from "antd/es/locale";
import enUS from "antd/es/locale/en_US";
import ruRU from "antd/es/locale/ru_RU";
import uzUZ from "antd/es/locale/uz_UZ";
import type { ReactNode } from "react";
import { I18nextProvider, useTranslation } from "react-i18next";

import i18n from "../shared/i18n";
import { createQueryClient } from "./queryClient";
import { appTheme } from "./theme";

const ANTD_LOCALES: Record<string, Locale> = { ru: ruRU, uz: uzUZ, en: enUS };

function ThemedApp({ children }: { children: ReactNode }) {
  const { i18n: instance } = useTranslation();
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
