import { App, Button, Tooltip } from "antd";
import { useTranslation } from "react-i18next";

import type { ProjectSigningInKind } from "../../../shared/api/generated/model";
import { useRequestEdsProjectSigning } from "../../../shared/api/generated/platform-bff";
import { useDeniedReason } from "../../../features/capabilities/useDeniedReason";
import { projectRef } from "./api";
import { useActionError } from "./errors";
import { useApplyCard } from "./useProjectMutations";

/** «На подпись»: документ уходит шагом «Подписать» уполномоченному в EDS (SIGN-4, ADR-0024). */
export function SigningButton({
  objectId,
  kind,
  documentId,
}: {
  objectId: string;
  kind: ProjectSigningInKind;
  documentId: number;
}) {
  const { t } = useTranslation("projects");
  const { message } = App.useApp();
  const apply = useApplyCard(objectId);
  // Отправка на подпись — действие раздела «Проекты» (полный доступ): без него кнопка закрыта, а не тихо отказывает (403).
  const denied = useDeniedReason("eds.projects", "full");
  const fail = useActionError(t("signing.failed"));
  const request = useRequestEdsProjectSigning({
    mutation: {
      onSuccess: (card) => {
        apply(card);
        void message.success(t("signing.sent"));
      },
      onError: fail,
    },
  });
  if (denied !== null) {
    return (
      <Tooltip title={denied} trigger={["hover", "focus"]}>
        <span className="pf-signing-denied" tabIndex={0} role="group" aria-label={denied}>
          <Button size="small" disabled>
            {t("signing.action")}
          </Button>
        </span>
      </Tooltip>
    );
  }
  return (
    <Button
      size="small"
      loading={request.isPending}
      onClick={() => {
        request.mutate({ ref: projectRef(objectId), data: { kind, document_id: documentId } });
      }}
    >
      {t("signing.action")}
    </Button>
  );
}
