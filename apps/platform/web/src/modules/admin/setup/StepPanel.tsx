import { Alert, Button } from "antd";
import { useTranslation } from "react-i18next";

import { InviteEmployeeForm } from "../../../features/invite-employee/InviteEmployeeForm";
import { STEP_ORDER } from "../../../entities/setup/steps";
import type { SetupStepKey, SetupStepState } from "../../../shared/api/generated/model";
import { ErpPanel } from "../integrations/ErpPanel";
import { MailPanel } from "../integrations/MailPanel";
import { ModelsPanel } from "../integrations/ModelsPanel";
import { TelegramPanel } from "../integrations/TelegramPanel";

import "../integrations/integrations.css";

/**
 * Форма шага первого запуска в боковом окне мастера (W15-H4, UX-оценка §5 P1-6): те же формы, что в «Подключениях» и
 * у «Сотрудников», но без перехода туда и обратно. Сверху — какой это шаг из пяти; когда шаг готов — «Дальше».
 */
export function StepPanel({
  step,
  state,
  next,
  onNext,
  onClose,
  onInvited,
}: {
  step: SetupStepKey;
  state: SetupStepState;
  /** Название следующего несделанного шага; нет — шаги закончились */
  next: string | null;
  onNext: () => void;
  onClose: () => void;
  /** Первый сотрудник создан (письмом или временным паролем): мастер перечитывает состояние */
  onInvited: () => void;
}) {
  const { t } = useTranslation("modules");
  const index = STEP_ORDER.indexOf(step) + 1;
  let form;
  switch (step) {
    case "erp":
      form = <ErpPanel editable />;
      break;
    case "bot":
      form = <TelegramPanel editable initialTokenOpen />;
      break;
    case "mail":
      form = <MailPanel editable />;
      break;
    case "models":
      form = <ModelsPanel editable />;
      break;
    case "first_employee":
      form = <InviteEmployeeForm onInvited={onInvited} onOpenCard={onInvited} onCancel={onClose} />;
      break;
  }
  const stepOf = t("admin.setup.stepOf", { index, total: STEP_ORDER.length });
  const title = t(`admin.setup.steps.${step}.title`);
  return (
    <section className="pf-panel-stack" aria-label={`${stepOf}: ${title}`}>
      <div>
        <p className="pf-hint" style={{ margin: 0 }}>
          {stepOf}
        </p>
        {/* У форм подключений свой заголовок (название карточки); у приглашения его нет — даём здесь */}
        {step === "first_employee" ? <h3 className="pf-setup-step-heading">{title}</h3> : null}
        <p className="pf-hint" style={{ margin: 0 }}>
          {t(`admin.setup.steps.${step}.text`)}
        </p>
      </div>
      {state === "done" ? (
        <Alert
          type="success"
          showIcon
          role="status"
          message={t("admin.setup.stepDone")}
          action={
            <Button type="primary" size="small" onClick={next ? onNext : onClose}>
              {next ? t("admin.setup.nextStep", { step: next }) : t("admin.setup.finish")}
            </Button>
          }
        />
      ) : null}
      {form}
    </section>
  );
}
