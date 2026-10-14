import { useUserStore } from '@/store/userStore';
import { useAuthStore } from '@/store/authStore';

/**
 * ADR-0005 U2 — client-side capability gate keyed on the member's effective CompanyRole
 * permissions (from /me.capabilities), NOT WorkspaceRole. Lets a delegated «Администратор
 * компании» (e.g. settings.edit / team.manage without the OWNER WorkspaceRole) reach the
 * company-admin surfaces the backend already authorizes them for.
 *
 * Lenient fallback: when permission data is absent (an older /me payload that predates
 * capabilities), fall back to the OWNER WorkspaceRole so the owner isn't locked out. This is
 * UX gating only — the backend (member_has_permission) remains the source of truth.
 */
export function useHasCompanyPermission(permission: string): boolean {
  const permissions = useUserStore((s) => s.capabilities.permissions);
  const isOwner = useAuthStore((s) => s.user?.workspace_role === 'OWNER');
  if (!permissions || permissions.length === 0) return isOwner;
  return permissions.includes(permission);
}

/**
 * Wave B2 (auto-claim) — true when the company effectively has only one member who can claim
 * work, so «Взять в работу» is pure noise (claim distributes work between teammates; with one it
 * distributes nothing). Имя флага (`is_solo_seller`) — поле бэкенда /me, переименуется вместе
 * с ролями бэк-офиса (M1-ERP-05). Drives HIDING the claim button, never a business gate — the backend still owns
 * claim/assignment. Reads the OPTIONAL `capabilities.is_solo_seller` flag the backend (B1) surfaces
 * on /me; while it is undefined this returns false and claim keeps its prior behaviour.
 */
export function useIsSoloSeller(): boolean {
  return useUserStore((s) => s.capabilities?.is_solo_seller === true);
}
