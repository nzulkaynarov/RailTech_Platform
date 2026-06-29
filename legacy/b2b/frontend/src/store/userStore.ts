import { create } from 'zustand';

/* ─── Company Status (what the company does on the platform) ──────────
   Two marketplace sides only: BUYER + SELLER. "Manufacturer" is an OEM brand
   reference (catalog.Manufacturer), not a participant role (retired 2026-06-23). */
export type CompanyStatus = 'BUYER' | 'SELLER';

export const companyStatusLabels: Record<CompanyStatus, string> = {
  BUYER: 'companyStatus.BUYER',
  SELLER: 'companyStatus.SELLER',
};

export const companyStatusDescriptions: Record<CompanyStatus, string> = {
  BUYER: 'companyStatusDesc.BUYER',
  SELLER: 'companyStatusDesc.SELLER',
};

/* ─── Verification status per company status ────────────────────────── */
export type VerificationStatus = 'pending' | 'verified' | 'rejected';

export const verificationLabels: Record<VerificationStatus, string> = {
  pending: 'verification.pending',
  verified: 'verification.verified',
  rejected: 'verification.rejected',
};

export interface CompanyStatusEntry {
  status: CompanyStatus;
  verification: VerificationStatus;
}

/* ─── System Role (Platform-level) ─────────────────────────────────────
 * After accounts/0010_platform_admin_model the only SystemRoles are ADMIN
 * (Platform Admin — owns the platform, no CompanyMember) and USER (everyone
 * else). The fine-grained "what can this user do inside their company" lives
 * in CompanyMember.role (WorkspaceRole) + can_sell / can_buy. See ADR-0002. */
export type UserRole = 'ADMIN' | 'USER';

export const roleLabels: Record<UserRole, string> = {
  ADMIN: 'roles.admin',
  USER: 'roles.user',
};

export const roleDescriptions: Record<UserRole, string> = {
  ADMIN: 'roles.adminDesc',
  USER: 'roles.userDesc',
};

/* ─── User Profile ──────────────────────────────────────────────────── */
export interface UserProfile {
  firstName: string;
  lastName: string;
  patronymic: string;
  email: string;
  phone: string;
  position: string;
  avatarInitials: string;
  avatarUrl: string | null;
}

/* ─── Company ───────────────────────────────────────────────────────── */
export interface Company {
  id: number | null;
  name: string;
  inn: string;
  kycStatus: 'verified' | 'pending' | 'not_started';
  country: string;
  city: string;
  logoUrl: string | null;
  /**
   * Each entry has its own verification status.
   * All statuses start as 'pending' until system admin approves.
   */
  statusEntries: CompanyStatusEntry[];
}

/* ─── App State (auth / onboarding) ─────────────────────────────────── */
export type AppScreen = 'onboarding' | 'pending_verification' | 'main';

/* ─── Store ─────────────────────────────────────────────────────────── */
interface UserState {
  screen: AppScreen;
  role: UserRole;
  activeStatus: CompanyStatus;
  profile: UserProfile;
  company: Company;
  /** True iff `role === 'ADMIN'`. Kept under its old name to avoid a wave of
   * renames across the call sites that still consume `isViewerMode`; semantics
   * are now simple: platform admin never operates within a company (migration
   * accounts/0010_platform_admin_model). The historical three-context synthetic
   * switcher has been replaced by `PlatformAdminShell` at the app level. */
  isViewerMode: boolean;
  /** Whether the seller company has an operational subscription. null for
   * non-sellers / before /me resolves. false → show the "subscription required"
   * banner (seller writes return SUBSCRIPTION_REQUIRED). */
  sellerSubscriptionOperational: boolean | null;
  /** Platform Engineer (Django superuser): full privileges everywhere. */
  isSuperuser: boolean;
  /** The platform operator's effective permission codes for client-side capability
   * gating (audit F3-UX). `null` = unrestricted (superuser, or an operator with no
   * sub-role assigned); an array = exactly the codes the assigned sub-role grants. */
  operatorPermissions: string[] | null;

  /* ── Auth integration ── */
  loadFromAuth: () => Promise<void>;

  /* ── Navigation ── */
  setActiveStatus: (status: CompanyStatus) => void;
  setRole: (role: UserRole) => void;
  updateProfile: (profile: Partial<UserProfile>) => void;
  updateCompany: (company: Partial<Company>) => void;
}

/* ─── Store ─────────────────────────────────────────────────────────── */

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const useUserStore = create<UserState>((set, _get) => ({
  /* Default: empty until loaded from auth. Default role is USER — an admin
   * default would make short-lived UI before auth finishes resolve into
   * admin-only screens. */
  screen: 'onboarding',
  role: 'USER',
  activeStatus: 'SELLER',
  isViewerMode: false,
  sellerSubscriptionOperational: null,
  isSuperuser: false,
  operatorPermissions: null,
  profile: {
    firstName: '',
    lastName: '',
    patronymic: '',
    email: '',
    phone: '',
    position: '',
    avatarInitials: '',
    avatarUrl: null,
  },
  company: {
    id: null,
    name: '',
    inn: '',
    kycStatus: 'not_started',
    country: '',
    city: '',
    logoUrl: null,
    statusEntries: [],
  },

  loadFromAuth: async () => {
    // Dynamic import to avoid circular dependency
    const { useAuthStore: authStoreHook } = await import('../store/authStore');
    const authState = authStoreHook.getState();
    if (authState.user) {
      const { first_name, last_name, email, phone, position, role_code, company, avatar } = authState.user;
      const initials = `${(first_name || '')[0] || ''}${(last_name || '')[0] || ''}`.toUpperCase();

      // Map backend company_types to frontend CompanyStatus
      // MANUFACTURER/PLANT were retired as participant roles → a selling company is
      // a SELLER; "manufacturer" now lives only as an OEM brand (catalog.Manufacturer).
      const typeMap: Record<string, CompanyStatus> = {
        CLIENT: 'BUYER',
        SUPPLIER: 'SELLER',
        MANUFACTURER: 'SELLER',
        PLANT: 'SELLER',
      };
      const companyTypes: string[] = company?.company_types ?? [];
      // Per-membership capabilities set by the company OWNER.
      // Default true so legacy users don't lose access; backend sends explicit
      // flags on next `/me/` refresh.
      const userPayload = authState.user as {
        can_sell?: boolean;
        can_buy?: boolean;
        seller_subscription_operational?: boolean | null;
        is_superuser?: boolean;
        operator_permissions?: string[] | null;
      };
      const canSell = userPayload.can_sell !== false;
      const canBuy = userPayload.can_buy !== false;
      const sellerSubscriptionOperational = userPayload.seller_subscription_operational ?? null;
      const isSuperuser = userPayload.is_superuser === true;
      const operatorPermissions = userPayload.operator_permissions ?? null;

      // Platform admin is decided purely by the backend-computed flag (see
      // CustomUser.is_platform_admin property) with a local fallback on role
      // code. Admins are rendered by PlatformAdminShell and never see the
      // three-context switcher, so no synthetic statusEntries are needed.
      const backendFlag = (userPayload as { is_platform_admin?: boolean }).is_platform_admin;
      const isPlatformAdmin = backendFlag ?? role_code === 'ADMIN';

      const rawEntries: CompanyStatusEntry[] = companyTypes.map((code) => ({
        status: typeMap[code] || 'BUYER',
        verification: 'verified' as const,
      }));
      // Filter out contexts the member may not use:
      //   can_sell=false → drop SELLER / MANUFACTURER
      //   can_buy=false  → drop BUYER
      const statusEntries: CompanyStatusEntry[] = rawEntries.filter((e) => {
        if (e.status === 'SELLER' && !canSell) return false;
        if (e.status === 'BUYER' && !canBuy) return false;
        return true;
      });
      // If OWNER revoked every capability we still keep BUYER as a safe fallback
      // so the app stays navigable (page-level guards do the fine-grained gating).
      const activeStatus: CompanyStatus = statusEntries.length > 0
        ? statusEntries[0].status
        : 'BUYER';

      set({
        screen: 'main',
        activeStatus,
        // Kept for backwards compatibility with call sites still reading
        // `isViewerMode`; see the UserState comment above.
        isViewerMode: isPlatformAdmin,
        sellerSubscriptionOperational,
        isSuperuser,
        operatorPermissions,
        role: isPlatformAdmin ? 'ADMIN' : 'USER',
        profile: {
          firstName: first_name || '',
          lastName: last_name || '',
          patronymic: '',
          email: email || '',
          phone: phone || '',
          position: position || '',
          avatarInitials: initials || '??',
          avatarUrl: avatar ?? null,
        },
        company: company ? {
          id: company.id ?? null,
          name: company.name || '',
          inn: company.inn || '',
          // Platform admin is a moderator, not a business actor — their personal
          // company's KYC state must not gate admin navigation. For regular users
          // we keep the real verification_status_code mapping.
          kycStatus: (isPlatformAdmin
            ? 'verified'
            : (['L2_VERIFIED', 'L3_CONTRACTED'].includes(company.verification_status_code ?? '') ? 'verified' : 'pending')
          ) as 'verified' | 'pending' | 'not_started',
          country: company.country != null ? String(company.country) : '',
          city: '',
          logoUrl: company.logo ?? null,
          statusEntries,
        } : {
          id: null,
          name: '',
          inn: '',
          // Platform admin has no company — KYC is not applicable, so we mark
          // 'verified' to keep KYC banners / guards out of admin nav.
          kycStatus: isPlatformAdmin ? 'verified' : 'not_started',
          country: '',
          city: '',
          logoUrl: null,
          statusEntries: [],
        },
      });
    }
  },

  setActiveStatus: (status) => set({ activeStatus: status }),
  setRole: (role) => set({ role }),
  updateProfile: (partial) =>
    set((s) => ({ profile: { ...s.profile, ...partial } })),
  updateCompany: (partial) =>
    set((s) => ({ company: { ...s.company, ...partial } })),
}));
