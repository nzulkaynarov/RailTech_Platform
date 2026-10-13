/**
 * Shared error/i18n helpers for the team settings package (moved verbatim from the
 * former monolithic Cabinet/CompanyTeamSettings.tsx — spec PR 4 package split).
 */
import type { TFunction } from 'i18next';

interface BackendErrorShape {
  response?: { data?: { error?: string; detail?: string } };
}

/** Backend service error codes → i18n message keys (see accounts/views/roles.py). */
const ROLE_ERROR_KEYS: Record<string, string> = {
  ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES: 'team.rolesSection.errors.onlyTeamManager',
  SYSTEM_ROLE_IMMUTABLE: 'team.rolesSection.errors.systemImmutable',
  ROLE_HAS_MEMBERS_REASSIGN_FIRST: 'team.rolesSection.errors.roleHasMembers',
  CANNOT_DEMOTE_LAST_COMPANY_ADMIN: 'team.rolesSection.errors.lastAdmin',
  MEMBER_NOT_FOUND: 'team.rolesSection.errors.memberNotFound',
  ROLE_NOT_FOUND: 'team.rolesSection.errors.roleNotFound',
  ROLE_NAME_REQUIRED: 'team.rolesSection.errors.nameRequired',
  ROLE_NAME_TAKEN: 'team.rolesSection.errors.nameTaken',
  UNKNOWN_PERMISSION_CODE: 'team.rolesSection.errors.unknownPermission',
  ROLE_COMPANY_MISMATCH: 'team.rolesSection.errors.companyMismatch',
};

/**
 * i18next uses '.' as its key separator, but permission codes contain dots
 * (e.g. "quote.build"). Map the dotted code to a single-segment key under
 * `permissions` so it resolves against the (nested) locale object.
 */
export function permLabelKey(code: string): string {
  return `permissions.${code.replace(/\./g, '_')}`;
}

/** Resolve a thrown axios error to a localized, human-readable message. */
export function resolveRoleError(err: unknown, translate: TFunction, fallbackKey: string): string {
  const data = (err as BackendErrorShape)?.response?.data;
  const code = data?.detail ?? data?.error;
  if (code && ROLE_ERROR_KEYS[code]) {
    return translate(ROLE_ERROR_KEYS[code]);
  }
  if (data?.detail) return data.detail;
  return translate(fallbackKey);
}
