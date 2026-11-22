import type { PickedCompany, PickedPerson } from "../../../shared/ui/pickers";

import type { FormValues } from "./formModel";

type Recipient = Pick<
  FormValues,
  | "recipientName"
  | "recipientInn"
  | "recipientCompanyId"
  | "recipientContactId"
  | "recipientEmail"
  | "recipientAttention"
>;

/** What the pickers filled on their own: only such values may be replaced or cleared when the choice changes */
export interface AutoFilled {
  person: PickedPerson | null;
  companyEmail: string;
}

export const NO_AUTO: AutoFilled = { person: null, companyEmail: "" };

/** «Кому» text a chosen person puts into the letter */
export const attentionOf = (person: PickedPerson): string =>
  [person.position, person.name].filter(Boolean).join(" ");

const autoEmail = (prev: Recipient, auto: AutoFilled): boolean =>
  auto.person?.email != null && prev.recipientEmail === auto.person.email;
const autoAttention = (prev: Recipient, auto: AutoFilled): boolean =>
  auto.person !== null && prev.recipientAttention === attentionOf(auto.person);

/** Company chosen or cleared: the previous company's person, email and «Кому» must not stay in the letter */
export function applyCompany(
  prev: Recipient,
  company: PickedCompany | null,
  auto: AutoFilled,
): Recipient {
  const nextId = company?.id ?? "";
  if (nextId === prev.recipientCompanyId) return prev;
  const hadCompany = prev.recipientCompanyId !== "";
  return {
    recipientName: company?.name ?? "",
    recipientInn: company?.inn ?? "",
    recipientCompanyId: nextId,
    recipientContactId: "",
    // the email from an incoming letter (reply) stays only while no company was chosen yet
    recipientEmail: company?.email ?? (hadCompany ? "" : prev.recipientEmail),
    recipientAttention: autoAttention(prev, auto) ? "" : prev.recipientAttention,
  };
}

/** Person chosen or cleared: email and «Кому» follow the person; no person — the company's shared email */
export function applyPerson(
  prev: Recipient,
  person: PickedPerson | null,
  auto: AutoFilled,
): Recipient {
  const ownEmail = autoEmail(prev, auto);
  const ownAttention = autoAttention(prev, auto);
  const fallbackEmail = auto.companyEmail;
  return {
    ...prev,
    recipientContactId: person?.id ?? "",
    recipientAttention: person ? attentionOf(person) : ownAttention ? "" : prev.recipientAttention,
    recipientEmail:
      person?.email ??
      (ownEmail || prev.recipientEmail === "" ? fallbackEmail : prev.recipientEmail),
  };
}
