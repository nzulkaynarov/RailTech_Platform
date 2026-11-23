import { isEmailLike } from "../../../shared/lib/email";

/** Одна проверка карточки поставщика: кнопка «Добавить», галочки шагов и список «нужно» берутся отсюда. */
export interface SupplierDraft {
  name: string;
  tin: string;
  reg: string;
  email: string;
}

export type SupplierRequirement = "name" | "tinOrReg" | "tinInvalid" | "emailInvalid";

export const TIN_PATTERN = /^\d{9}$/;

/** Невыполненные требования по шагам «Компания» и «Контакт»; пусто — шаг готов к отправке. */
export function supplierRequirements(draft: SupplierDraft): {
  company: SupplierRequirement[];
  contact: SupplierRequirement[];
} {
  const company: SupplierRequirement[] = [];
  if (draft.name.trim() === "") company.push("name");
  if (draft.tin.trim() === "" && draft.reg.trim() === "") company.push("tinOrReg");
  if (draft.tin.trim() !== "" && !TIN_PATTERN.test(draft.tin.trim())) company.push("tinInvalid");
  const contact: SupplierRequirement[] = [];
  if (draft.email.trim() !== "" && !isEmailLike(draft.email)) contact.push("emailInvalid");
  return { company, contact };
}
