import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { cardFact } from "../../../entities/status/facts";
import type {
  IntegrationCardKey,
  IntegrationsOverview,
  StatusState,
} from "../../../shared/api/generated/model";
import {
  checkErpConnector,
  checkExternalService,
  getGetIntegrationsOverviewQueryKey,
  getIntegrationsOverview,
  listExternalServices,
} from "../../../shared/api/generated/platform-bff";
import { integrationErrorText } from "./errors";

export interface CheckOutcome {
  /** Слово состояния карточки ПОСЛЕ проверки (из свежего ответа сервера) или ошибка самой проверки */
  state: StatusState | "error";
  text: string;
}

/** Сервисы реестра CRM, которые проверяет «Проверить» карточки: то, что названо в её подписи (`cards.<key>.scope`). */
const CARD_SERVICES: Partial<Record<IntegrationCardKey, (key: string) => boolean>> = {
  telegram: (key) => key === "telegram",
  mail: (key) => key === "mail" || key === "mail_inbound",
  services: () => true,
  models: (key) => key === "litellm" || key.startsWith("vendor."),
  storage: (key) => ["s3", "backup", "wal_archive", "offsite_backup"].includes(key),
};

/**
 * «Проверить» на карточке (НАСТ-П1, аудит §6.2 п. 6): запускает проверку того, что названо на карточке, ждёт ответ,
 * перечитывает обзор и только после этого пишет итог — словом из свежей карточки, а не из ответа самой пробы. Итог
 * хранит CRM (реестр сервисов, у ERP — живая проба «Состояния системы»), поэтому карточка меняется и сама.
 * «Расходы» и «Состояние системы» — отчёты: «Обновить» ждёт ответа сервера и только потом пишет «Данные обновлены».
 */
export function useCardCheck() {
  const { t } = useTranslation(["integrations", "ui"]);
  const queryClient = useQueryClient();
  const [running, setRunning] = useState<IntegrationCardKey | null>(null);
  const [outcomes, setOutcomes] = useState<Partial<Record<IntegrationCardKey, CheckOutcome>>>({});

  /** Свежий обзор: положить в кэш (карточки на экране обновятся) и вернуть слово нужной карточки. */
  const reload = async (key: IntegrationCardKey): Promise<StatusState> => {
    const fresh: IntegrationsOverview = await getIntegrationsOverview();
    queryClient.setQueryData(getGetIntegrationsOverviewQueryKey(), fresh);
    void queryClient.invalidateQueries({
      predicate: (query) =>
        String(query.queryKey[0]).startsWith("/api/v1/admin/integrations") &&
        query.queryKey[0] !== getGetIntegrationsOverviewQueryKey()[0],
    });
    return cardFact(fresh, key).state;
  };

  const probe = async (key: IntegrationCardKey): Promise<void> => {
    if (key === "erp") {
      await checkErpConnector();
      return;
    }
    const match = CARD_SERVICES[key];
    if (!match) return;
    const list = await listExternalServices();
    await Promise.all(
      list.items
        .filter((service) => service.status !== "off" && match(service.key))
        .map((service) => checkExternalService(service.key)),
    );
  };

  const start = async (key: IntegrationCardKey) => {
    setRunning(key);
    setOutcomes((prev) => ({ ...prev, [key]: undefined }));
    try {
      const isReport = key === "spend" || key === "system";
      if (!isReport) await probe(key);
      const state = await reload(key);
      setOutcomes((prev) => ({
        ...prev,
        [key]: {
          state,
          text: isReport
            ? t("check.refreshed")
            : t("check.result", { status: t(`ui:statusStrip.state.${state}`) }),
        },
      }));
    } catch (error) {
      setOutcomes((prev) => ({
        ...prev,
        [key]: { state: "error", text: integrationErrorText(t, error) },
      }));
    } finally {
      setRunning(null);
    }
  };
  return { running, outcomes, start };
}
