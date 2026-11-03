import { Alert, Button } from "antd";
import { useTranslation } from "react-i18next";

import type { InboundMail } from "../../../shared/api/generated/model";
import { releaseInboundMail } from "../../../shared/api/generated/platform-bff";
import { useMailRun } from "./useMailRun";

/** «Вернуть в Новые» (первая линия) или «Вернуть делопроизводителю» (сотрудник со своим письмом). */
export function ReleaseButton({
  mail,
  label,
  reload,
}: {
  mail: InboundMail;
  label: string;
  reload: () => void;
}) {
  const { t } = useTranslation("letters");
  const { run, pending, error } = useMailRun(reload);
  return (
    <div className="pf-mail-actions">
      <div>
        <Button
          loading={pending}
          onClick={() =>
            void run(async () => {
              await releaseInboundMail(mail.id);
              return t("mail.returned");
            }, reload)
          }
        >
          {label}
        </Button>
      </div>
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
    </div>
  );
}
