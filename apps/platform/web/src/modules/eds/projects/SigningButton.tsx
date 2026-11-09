import { App, Button } from "antd";
import { useTranslation } from "react-i18next";

import type { ProjectSigningInKind } from "../../../shared/api/generated/model";
import { useRequestEdsProjectSigning } from "../../../shared/api/generated/platform-bff";
import { projectRef } from "./api";
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
  const request = useRequestEdsProjectSigning({
    mutation: {
      onSuccess: (card) => {
        apply(card);
        void message.success(t("signing.sent"));
      },
      onError: () => {
        void message.error(t("signing.failed"));
      },
    },
  });
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
