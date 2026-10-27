import { useTranslation } from "react-i18next";

import { STEP_TARGET } from "../../../entities/setup/steps";
import type { SetupStep, SetupStepState } from "../../../shared/api/generated/model";
import type { StatusTone } from "../../../shared/lib/statuses";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";

import "../../../features/first-run/first-run.css";

const TONE: Record<SetupStepState, StatusTone> = {
  done: "green",
  todo: "gold",
  unknown: "default",
};

/**
 * Пять шагов чек-листа (SPEC-v3 §7.6): статус словом и одна ссылка на экран, где шаг делается. Сделанный шаг остаётся
 * в списке — ссылка ведёт на тот же экран, чтобы проверить или изменить настройку.
 */
export function ConnectionsStep({ steps }: { steps: readonly SetupStep[] }) {
  const { t } = useTranslation("modules");
  return (
    <ul className="pf-setup-steps" aria-label={t("admin.setup.listLabel")}>
      {steps.map((step) => (
        <li key={step.key} className="pf-setup-step" data-step={step.key}>
          <div className="pf-setup-step-text">
            <span className="pf-setup-step-title">
              {t(`admin.setup.steps.${step.key}.title`)}
              <StatusTag tone={TONE[step.state]}>{t(`admin.setup.state.${step.state}`)}</StatusTag>
            </span>
            <span className="pf-hint">{t(`admin.setup.steps.${step.key}.text`)}</span>
          </div>
          <LinkButton
            type={step.state === "todo" ? "primary" : "default"}
            to={STEP_TARGET[step.key]}
          >
            {t(`admin.setup.steps.${step.key}.action`)}
          </LinkButton>
        </li>
      ))}
    </ul>
  );
}
