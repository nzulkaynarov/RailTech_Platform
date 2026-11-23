import { isEmailLike } from "../../../shared/lib/email";

/** Одна проверка «Реквизитов»: галочки шагов «Компания» и «Контакты» и их список «нужно» берутся отсюда. */
export interface DetailsDraft {
  name?: string | null | undefined;
  inn?: string | null | undefined;
  legal_address?: string | null | undefined;
  phone?: string | null | undefined;
  email?: string | null | undefined;
}

export type DetailsRequirement =
  | "nameRequired"
  | "innRequired"
  | "innInvalid"
  | "addressRequired"
  | "contactRequired"
  | "emailInvalid";

const INN = /^\d{9}$/;

/**
 * Невыполненные требования по шагам. ИНН и адрес не мешают сохранить, но без них нет реквизитов для счетов (СЦ-3):
 * шаг не отмечается готовым, пока их нет.
 */
export function detailsRequirements(draft: DetailsDraft): {
  company: DetailsRequirement[];
  contacts: DetailsRequirement[];
} {
  const company: DetailsRequirement[] = [];
  if (!(draft.name ?? "").trim()) company.push("nameRequired");
  const inn = (draft.inn ?? "").trim();
  if (!inn) company.push("innRequired");
  else if (!INN.test(inn)) company.push("innInvalid");
  const contacts: DetailsRequirement[] = [];
  if (!(draft.legal_address ?? "").trim()) contacts.push("addressRequired");
  const email = (draft.email ?? "").trim();
  if (!(draft.phone ?? "").trim() && !email) contacts.push("contactRequired");
  if (email && !isEmailLike(email)) contacts.push("emailInvalid");
  return { company, contacts };
}
