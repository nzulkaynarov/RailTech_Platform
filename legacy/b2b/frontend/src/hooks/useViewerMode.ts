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
