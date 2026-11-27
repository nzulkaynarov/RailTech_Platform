import { useTranslation } from "react-i18next";

import { type VisibleStep, visibleTitleKey } from "../../../entities/setup/steps";
import { STEP_CARD } from "../../../entities/status/facts";
import type { IntegrationCardKey } from "../../../shared/api/generated/model";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusStrip } from "../../../shared/ui/StatusStrip";
import { StatusTag } from "../../../shared/ui/StatusTag";

import "../../../features/first-run/first-run.css";

/** Текст и кнопка строки: у шагов чек-листа — свои ключи, у «Прав подписи» (СЦ-3) — `admin.setup.signing`. */
function textKey(step: VisibleStep, part: "text" | "action"): string {
  return step.key === "signing"
    ? `admin.setup.signing.${part}`
    : `admin.setup.steps.${step.key}.${part}`;
}

/**
 * Остальные шаги первого запуска (SPEC-v3 §7.6): статус словом и одна ссылка на экран, где шаг делается. Сделанный шаг
 * остаётся в списке — ссылка ведёт на тот же экран, чтобы проверить или изменить настройку.
 */
export function ConnectionsStep({ steps }: { steps: readonly VisibleStep[] }) {
  const { t } = useTranslation(["modules", "integrations"]);
  return (
    <ul className="pf-setup-steps" aria-label={t("admin.setup.listLabel")}>
      {steps.map((step) => (
        <li key={step.key} className="pf-setup-step" data-step={step.key}>
          <div className="pf-setup-step-text">
            <span className="pf-setup-step-title">
              {t(visibleTitleKey(step.key))}
              {step.fact && step.state === "done" ? (
                // Шаг службы «Готово» только словом проверки службы — тем же, что на «Состоянии» и в «Сервисах»
                <StatusStrip
                  fact={step.fact}
                  scope={t(
                    `integrations:cards.${(STEP_CARD as Record<string, IntegrationCardKey>)[step.key] ?? "erp"}.scope`,
                  )}
                />
              ) : (
                <StatusTag kind="setupStep" status={step.state}>
                  {/* Проверка не выполнялась — не «Готово» и не «Нет данных» (O-4, W15-H3) */}
                  {step.state === "unknown"
                    ? t("integrations:health.setupUnchecked")
                    : t(`admin.setup.state.${step.state}`)}
                </StatusTag>
              )}
            </span>
            <span className="pf-hint">{t(textKey(step, "text"))}</span>
          </div>
          <LinkButton type={step.state === "todo" ? "primary" : "default"} to={step.to}>
            {t(textKey(step, "action"))}
          </LinkButton>
        </li>
      ))}
    </ul>
  );
}
