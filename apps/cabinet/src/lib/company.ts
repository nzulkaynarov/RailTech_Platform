import type { Company, CompanyUpdate, Schemas, TeamInvite } from '@/api/portal';

/** Только изменённые поля профиля — `PUT /company` не перетирает то, что клиент не трогал. */
export function companyChanges(company: Company, draft: Required<CompanyUpdate>): CompanyUpdate {
  const changes: CompanyUpdate = {};
  const name = draft.name.trim();
  if (name !== company.name) changes.name = name;
  if (draft.inn.trim() !== (company.inn ?? '')) changes.inn = draft.inn.trim();
  if (draft.legal_address.trim() !== (company.legal_address ?? '')) changes.legal_address = draft.legal_address.trim();
  if (draft.bank_details.trim() !== (company.bank_details ?? '')) changes.bank_details = draft.bank_details.trim();
  if (draft.language !== company.language) changes.language = draft.language;
  return changes;
}

export interface InviteDraft {
  name: string;
  email: string;
  phone: string;
  language: Schemas['Language'];
  can_act: boolean;
  channels: { email: boolean; telegram: boolean };
}

/** Что не так с приглашением — ключи `pages.team.problems.*`. */
export type InviteProblem = 'name' | 'channels' | 'email' | 'phone';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE = /^\+?[\d\s()-]{7,32}$/;

/**
 * Приглашение коллеги (`TeamInvite`): нужен хотя бы один канал; для e-mail — адрес, для Telegram —
 * телефон (по нему бот узнаёт человека, M2-ERP-02). Пустые поля в тело не попадают.
 */
export function validateInvite(
  draft: InviteDraft,
): { ok: true; body: TeamInvite } | { ok: false; problems: InviteProblem[] } {
  const problems: InviteProblem[] = [];
  const name = draft.name.trim();
  const email = draft.email.trim();
  const phone = draft.phone.trim();
  const channels = (['email', 'telegram'] as const).filter((channel) => draft.channels[channel]);
  if (!name) problems.push('name');
  if (channels.length === 0) problems.push('channels');
  if ((draft.channels.email || email) && !EMAIL_RE.test(email)) problems.push('email');
  if ((draft.channels.telegram || phone) && !PHONE_RE.test(phone)) problems.push('phone');
  if (problems.length) return { ok: false, problems };
  const body: TeamInvite = { name, language: draft.language, can_act: draft.can_act, channels };
  if (email) body.email = email;
  if (phone) body.phone = phone;
  return { ok: true, body };
}
