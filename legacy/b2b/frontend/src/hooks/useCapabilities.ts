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
