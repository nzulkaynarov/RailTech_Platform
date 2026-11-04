import { useState } from "react";

import type { CatalogDocumentKind } from "../../../shared/api/generated/model";

/** Паспорт документа товара (CAT-CARD-1): вид из справочника, номер, кем выдан, даты, «видно клиенту». */
export interface DocPassport {
  kind: string;
  number: string;
  issuedBy: string;
  issuedAt: string;
  validUntil: string;
  clientVisible: boolean;
  /** Сотрудник сам трогал «Видно клиенту»: смена вида больше не подставляет значение вида. */
  visibleTouched: boolean;
}

/** Начальный паспорт: вид по умолчанию — первый активный из справочника, «видно клиенту» — по виду. */
export function emptyPassport(kinds: readonly CatalogDocumentKind[]): DocPassport {
  const first = kinds.find((k) => k.code === "other") ?? kinds[0];
  return {
    kind: first?.code ?? "other",
    number: "",
    issuedBy: "",
    issuedAt: "",
    validUntil: "",
    clientVisible: first?.client_visible_default ?? false,
    visibleTouched: false,
  };
}

/** Состояние паспорта в форме: пока сотрудник ничего не менял, значения берутся из справочника (он может прийти позже). */
export function usePassport(kinds: readonly CatalogDocumentKind[], initial?: DocPassport) {
  const [edited, setEdited] = useState<DocPassport | null>(initial ?? null);
  return [edited ?? emptyPassport(kinds), setEdited] as const;
}

/** Поля паспорта для запроса: пустые даты не отправляются при создании. */
export function passportFields(p: DocPassport) {
  return {
    kind: p.kind,
    ...(p.number.trim() ? { number: p.number.trim() } : {}),
    ...(p.issuedBy.trim() ? { issued_by: p.issuedBy.trim() } : {}),
    ...(p.issuedAt ? { issued_at: p.issuedAt } : {}),
    ...(p.validUntil ? { valid_until: p.validUntil } : {}),
    client_visible: p.clientVisible,
  };
}
