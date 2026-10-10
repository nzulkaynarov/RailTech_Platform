import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp } from "antd";

import {
  createManualDocument,
  reingestKbDocument,
  updateKbDocument,
  uploadKbDocument,
} from "../../api/generated/crm";
import type { KbDocumentOut } from "../../api/generated/model";
import { unwrap } from "../../api/http";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import type { ManualValues, UploadValues } from "./KbDialogs";

const named = (text: string, d: KbDocumentOut) => text.replace("{title}", d.title);

/** Мутации базы знаний; тост называет, что произошло и с каким документом. */
export function useKbMutations(onCreated: () => void) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const refresh = () => client.invalidateQueries({ queryKey: ["kb"] });
  const created = () => {
    onCreated();
    void refresh();
    void message.success(t.kb.uploaded);
  };
  return {
    upload: useMutation({
      mutationFn: async (v: UploadValues) => {
        const file = v.file[0]?.originFileObj;
        if (!file) throw new Error(t.kb.file);
        const body = { file, title: v.title, language: v.language };
        return unwrap(await uploadKbDocument({ ...body, product_key: v.product_key ?? null }));
      },
      onSuccess: created,
      onError,
    }),
    manual: useMutation({
      mutationFn: async (v: ManualValues) =>
        unwrap(await createManualDocument({ ...v, product_key: v.product_key ?? null })),
      onSuccess: created,
      onError,
    }),
    toggle: useMutation({
      mutationFn: async (d: KbDocumentOut) =>
        unwrap(await updateKbDocument(d.id, { is_active: !d.is_active })),
      onSuccess: (_, d) => {
        void refresh();
        void message.success(named(d.is_active ? t.kb.deactivated : t.kb.activated, d));
      },
      onError,
    }),
    reingest: useMutation({
      mutationFn: async (d: KbDocumentOut) => unwrap(await reingestKbDocument(d.id)),
      onSuccess: (_, d) => {
        void refresh();
        void message.success(named(t.kb.reingested, d));
      },
      onError,
    }),
  };
}
