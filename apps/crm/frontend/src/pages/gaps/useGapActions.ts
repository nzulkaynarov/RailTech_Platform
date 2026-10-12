import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp } from "antd";

import { createManualDocument, ignoreGap, reopenGap, resolveGap } from "../../api/generated/crm";
import type { KbGapOut } from "../../api/generated/model";
import { invalidateKeys, queryKeys } from "../../api/queryKeys";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import type { ManualValues } from "../kb/KbDialogs";

export type GapAction =
  | { kind: "ignore" | "reopen"; gap: KbGapOut }
  | { kind: "link"; gap: KbGapOut; documentId: number };

const DONE: Record<GapAction["kind"], string> = {
  link: t.gaps.linked,
  ignore: t.gaps.ignored,
  reopen: t.gaps.reopened,
};

async function run(a: GapAction) {
  if (a.kind === "link") return await resolveGap(a.gap.id, { document_id: a.documentId });
  if (a.kind === "ignore") return await ignoreGap(a.gap.id);
  return await reopenGap(a.gap.id);
}

/** Действия над пробелом и создание документа из вопроса; тост — по действию. */
export function useGapActions(onDone: () => void) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const finish = (text: string) => {
    onDone();
    void invalidateKeys(client, queryKeys.kb());
    void message.success(text);
  };
  const act = useMutation({
    mutationFn: run,
    onSuccess: (_, a) => {
      finish(DONE[a.kind]);
    },
    onError,
  });
  const create = useMutation({
    mutationFn: async (v: ManualValues & { gapId: number }) =>
      await createManualDocument({
        title: v.title,
        markdown: v.markdown,
        language: v.language,
        product_key: v.product_key ?? null,
        gap_id: v.gapId,
      }),
    onSuccess: () => {
      finish(t.gaps.created);
    },
    onError,
  });
  return { act, create };
}
