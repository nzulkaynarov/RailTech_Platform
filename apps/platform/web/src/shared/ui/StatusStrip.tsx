import { Button } from "antd";
import { useTranslation } from "react-i18next";

import type { StatusFact, StatusState } from "../api/generated/model";
import { agoText } from "../lib/ago";
import { StatusTag } from "./StatusTag";

import "./ui.css";

/** Цвет слова — из единственной карты `STATUS_TONE` (вид `integration`): «не проверено» и «нет данных» не зелёные. */
const TONE: Record<StatusState, "ok" | "warn" | "fail" | "unknown" | "off"> = {
  works: "ok",
  attention: "warn",
  broken: "fail",
  not_verified: "unknown",
  stale: "unknown",
  unknown: "unknown",
  off: "off",
};

export interface StatusStripProps {
  /**
   * Модель статуса из ответа BFF: слово, время проверки и на чём оно держится. Целиком обязательна: слово без времени
   * проверки и источника не компилируется (аудит Настроек §6.2: «Работает» только по живой проверке).
   */
  fact: StatusFact;
  /** Что именно проверено («связь с расчётами», «шлюз и ключи моделей»): подпись равна проверенному */
  scope: string;
  /** «Проверить сейчас»: проверяет то, что названо в `scope`, и сохраняет итог; без обработчика кнопки нет */
  onCheck?: () => void;
  checking?: boolean;
  /** Подпись кнопки для скринридера с названием службы; должна содержать видимое слово кнопки */
  checkAria?: string;
  /** Слово кнопки вместо «Проверить» (у отчётов — «Обновить») */
  checkLabel?: string;
  /** Для тестов: «сейчас» для подписи «проверено …» */
  now?: Date;
}

/**
 * Полоса статуса (НАСТ-П1): слово состояния + что проверено + когда + «Проверить сейчас». Единственный вид статуса
 * службы на «Состоянии», карточках «Сервисов» и шагах мастера: слово не выбирается на месте, оно приходит в `fact`.
 */
export function StatusStrip({
  fact,
  scope,
  onCheck,
  checking,
  checkAria,
  checkLabel,
  now,
}: StatusStripProps) {
  const { t, i18n } = useTranslation("ui");
  const when =
    fact.checked_at !== null
      ? t("statusStrip.checkedAgo", { when: agoText(i18n.language, fact.checked_at, now) })
      : fact.state === "off"
        ? null
        : t("statusStrip.never");
  return (
    <span className="pf-status-strip" data-state={fact.state} data-source={fact.source}>
      <StatusTag kind="integration" status={TONE[fact.state]}>
        {t(`statusStrip.state.${fact.state}`)}
      </StatusTag>
      <span className="pf-status-strip-text">
        {scope}
        {when ? ` · ${when}` : ""}
      </span>
      {onCheck ? (
        <Button size="small" loading={checking} aria-label={checkAria} onClick={onCheck}>
          {checkLabel ?? t("statusStrip.check")}
        </Button>
      ) : null}
    </span>
  );
}
