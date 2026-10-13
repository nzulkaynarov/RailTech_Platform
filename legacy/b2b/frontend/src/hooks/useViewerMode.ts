import { useUserStore } from '@/store/userStore';

/**
 * Returns true when the current user is a platform admin in viewer mode —
 * sees all 3 contexts (BUYER / SELLER / MANUFACTURER) but must not execute
 * business actions on behalf of any company. Backend independently rejects
 * such writes with `ADMIN_VIEWER_CANNOT_ACT`; this hook drives UX-level
 * defense-in-depth by disabling action buttons before the request is sent.
 *
 * See: ADR-0002, memory `admin_viewer_mode_2026_04_19.md`.
 */
export function useIsViewerMode(): boolean {
  return useUserStore((s) => s.isViewerMode);
}

/**
 * Client-side capability gate for the Platform Operator plane (audit F3-UX).
 *
 * Returns true when the current operator may perform `permission` (e.g. `operators.manage`,
 * `kyc.verify`, `billing.manage`). Mirrors the backend `operator_has_permission`:
 *   - superuser → always true (full privileges)
 *   - no sub-role assigned (operatorPermissions === null) → true (backward-compat full access)
 *   - otherwise → true only if the code is in the operator's granted set
 *
 * Use it to HIDE mutation controls a narrow sub-role can't use, instead of showing them and
 * letting the action 403 on save. The backend remains the source of truth (defense-in-depth).
 */
export function useOperatorCan(permission: string): boolean {
  return useUserStore((s) => {
    if (s.isSuperuser) return true;
    if (s.operatorPermissions === null) return true;
    return s.operatorPermissions.includes(permission);
  });
}
