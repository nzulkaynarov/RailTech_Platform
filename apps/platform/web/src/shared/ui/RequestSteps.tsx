import { useTranslation } from "react-i18next";

import { STAGES, type StageOrLost } from "../lib/statuses";
import { CheckIcon } from "./icons";
import { StatusTag } from "./StatusTag";
import "./ui.css";

export interface RequestStepsProps {
  /** Стадия из шкалы SPEC-v3 §2.3 или `LOST` («Отказ» — тег рядом со шкалой) */
  stage: StageOrLost;
  /** Только для `LOST`: номер шага (1–7), на котором закрыли заявку; пройденные до него шаги остаются заливкой */
  step?: number;
  /** Номер заявки/проекта для имени шкалы: «Путь заявки ЗВ-2026-104» */
  number?: string;
}

type StepState = "done" | "current" | "upcoming";

function stateOf(index: number, stage: StageOrLost, step: number | undefined): StepState {
  if (stage === "LOST") return step !== undefined && index + 1 < step ? "done" : "upcoming";
  // «Выполнено» — конечная точка: все семь шагов пройдены, текущего нет
  if (stage === "DONE") return "done";
  const current = STAGES.indexOf(stage);
  if (index < current) return "done";
  return index === current ? "current" : "upcoming";
}

/**
 * Шкала из 7 шагов на карточках заявки и проекта (SPEC-v3 §2.3; docs/architecture/platform-frontend.md §5). Круг 24 px, номер 12/500; пройденный —
 * заливка `#1668dc` с галочкой, текущий — рамка `#1668dc` на `#e6f4ff`, будущий — рамка `#d9d9d9`; соединитель 1 px;
 * подпись 13 px с многоточием. Состояние дублируется словом для скринридера (`aria-current="step"`), на узкой ширине
 * подпись остаётся только у текущего шага.
 */
export function RequestSteps({ stage, step, number }: RequestStepsProps) {
  const { t } = useTranslation(["dictionary", "ui"]);
  const label = number ? t("ui:steps.labelNumber", { number }) : t("ui:steps.label");
  return (
    <div className="pf-steps-row">
      <div className="pf-steps-box">
        <ol className="pf-steps" aria-label={label}>
          {STAGES.map((code, index) => {
            const state = stateOf(index, stage, step);
            return (
              <li
                key={code}
                className={`pf-step pf-step--${state}`}
                aria-current={state === "current" ? "step" : undefined}
              >
                <span className="pf-step-num" aria-hidden="true">
                  {state === "done" ? <CheckIcon /> : index + 1}
                </span>
                <span className="pf-step-label">
                  {t(`dictionary:stage.${code}`)}
                  <span className="pf-sr-only">, {t(`ui:steps.${state}`)}</span>
                </span>
                {index < STAGES.length - 1 ? (
                  <span className="pf-step-line" aria-hidden="true" />
                ) : null}
              </li>
            );
          })}
        </ol>
      </div>
      {stage === "LOST" ? (
        <StatusTag kind="stage" status="LOST">
          {t("dictionary:stage.LOST")}
          {step !== undefined ? (
            <span className="pf-sr-only"> ({t("ui:steps.lostAt", { step })})</span>
          ) : null}
        </StatusTag>
      ) : null}
    </div>
  );
}
