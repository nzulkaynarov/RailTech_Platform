import { Alert } from "antd";
import { useTranslation } from "react-i18next";

import type { EscalationDryRun } from "../../../shared/api/generated/model";
import { LeadRef } from "../../crm/kb/GapsView";

function Codes({ codes }: { codes: readonly string[] }) {
  const { t } = useTranslation(["bot", "kb"]);
  if (codes.length === 0) return <>{t("bot:dryRun.noReasons")}</>;
  return <>{codes.map((c) => t(`kb:triggers.${c}`, { defaultValue: c })).join(", ")}</>;
}

/** Итог пробного прогона: сколько передач менеджеру сейчас и с новыми правилами, какие лиды изменятся. */
export function DryRunPanel({ report }: { report: EscalationDryRun }) {
  const { t } = useTranslation("bot");
  return (
    <div className="pf-bot-dryrun" role="status" aria-label={t("dryRun.result")}>
      <dl className="pf-bot-tiles">
        <div>
          <dt>{t("dryRun.dialogs")}</dt>
          <dd>{report.dialogs}</dd>
        </div>
        <div>
          <dt>{t("dryRun.now")}</dt>
          <dd>{report.escalated_current}</dd>
        </div>
        <div>
          <dt>{t("dryRun.new")}</dt>
          <dd>{report.escalated_candidate}</dd>
        </div>
      </dl>
      {report.changed.length === 0 ? (
        <Alert type="info" showIcon message={t("dryRun.nothingChanges")} />
      ) : (
        <>
          <h4 className="pf-bot-subtitle">
            {t("dryRun.changed", { count: report.changed.length })}
          </h4>
          <ul className="pf-bot-changed">
            {report.changed.map((row) => (
              <li key={row.run_id}>
                <LeadRef id={row.lead_id} />
                <span>
                  <Codes codes={row.current} />
                </span>
                <span aria-hidden="true">→</span>
                <span className="pf-sr-only">{t("dryRun.becomes")}</span>
                <span>
                  <Codes codes={row.candidate} />
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
