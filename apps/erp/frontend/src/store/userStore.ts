import { create } from 'zustand';
import i18n from '@/i18n';
import { useThemeStore } from './themeStore';

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

export interface CompanyStatusEntry {
  status: CompanyStatus;
}

/** Consolidated effective capabilities (mirrors backend MeSerializer.capabilities, ADR-0005).
 * Single source the unified nav engine (config/navigation.tsx) reads to render/gate items. */
export interface Capabilities {
  can_buy: boolean;
  can_sell: boolean;
  permissions: string[];
  /** Wave B2 (auto-claim) — true when the seller company effectively has ONE member with claim
   * rights, so «Взять в работу» is noise (there is no one to route work between). OPTIONAL: the
   * parallel backend (B1) lane adds it to /me.capabilities; until then it is undefined and the
   * claim button keeps its prior behaviour. UI-gating only — claim/assignment stays authoritative
   * server-side. See useIsSoloSeller. */
  is_solo_seller?: boolean;
  /**
   * Дневной расход ИИ. Не гейт, а ИНФОРМАЦИЯ рядом с кнопкой ИИ: потолок живёт на сервере
   * (429 `AI_DAILY_CAP_REACHED`) как защита бюджета, не как тариф. Новых блокировок нет —
   * только показ остатка. `null` в потолке и остатке = безлимит (это НЕ то же, что остаток 0).
   */
  ai_daily_used?: number;
  ai_daily_cap?: number | null;
  ai_daily_remaining?: number | null;
}

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
  is_2fa_enabled?: boolean;
}

/* ─── Company ───────────────────────────────────────────────────────── */
export interface Company {
  id: number | null;
  name: string;
  inn: string;
  country: string;
  city: string;
  logoUrl: string | null;
  statusEntries: CompanyStatusEntry[];
}

/* ─── App State: 'loading' until loadFromAuth() resolves /me, then 'main' ── */
export type AppScreen = 'loading' | 'main';

/* ─── Store ─────────────────────────────────────────────────────────── */
interface UserState {
  screen: AppScreen;
  activeStatus: CompanyStatus;
  profile: UserProfile;
  company: Company;
  /** ADR-0005: consolidated capability object driving the unified nav engine. */
  capabilities: Capabilities;

  /* ── Auth integration ── */
  loadFromAuth: () => Promise<void>;

  /* ── Navigation ── */
  setActiveStatus: (status: CompanyStatus) => void;
  updateProfile: (profile: Partial<UserProfile>) => void;
  updateCompany: (company: Partial<Company>) => void;
}

/* ─── Store ─────────────────────────────────────────────────────────── */

export const useUserStore = create<UserState>((set, get) => ({
  /* Default: empty until loaded from auth. */
  screen: 'loading',
  /* Pre-auth default context is the NARROWEST/safest side, BUYER. It matches the
   * `|| 'BUYER'` fallback in api/client.ts (X-Active-Context) and the
   * `statusEntries.length === 0 ? 'BUYER'` fallback in loadFromAuth, so cold-load
   * requests never go out under a wider seller scope before /me resolves. */
  activeStatus: 'BUYER',
  capabilities: {
    can_buy: true, can_sell: true,
    permissions: [],
  },
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
      const { first_name, last_name, email, phone, position, company, avatar } = authState.user;
      // Nameless accounts (e.g. init_superadmin) fall back to the email local part
      // so the avatar never renders the "??" placeholder.
      const initials = (
        `${(first_name || '')[0] || ''}${(last_name || '')[0] || ''}` || (email || '').slice(0, 2)
      ).toUpperCase();

      const prefs = authState.user.preferences;
      if (prefs) {
        if (prefs.language && prefs.language !== i18n.language) {
          i18n.changeLanguage(prefs.language);
        }
        if (prefs.theme) {
          useThemeStore.getState().setTheme(prefs.theme as 'light' | 'dark');
        }
      }

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
        capabilities?: Capabilities;
      };
      const canSell = userPayload.can_sell !== false;
      const canBuy = userPayload.can_buy !== false;

      const rawEntries: CompanyStatusEntry[] = companyTypes.map((code) => ({
        status: typeMap[code] || 'BUYER',
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

      // ADR-0005: prefer the backend's consolidated capability object; synthesize a safe
      // fallback from the legacy flags if an older /me payload omits it (empty permissions →
      // the nav engine treats perm-gates as "unknown" and doesn't over-hide; backend enforces).
      const capabilities: Capabilities = userPayload.capabilities ?? {
        can_buy: canBuy,
        can_sell: canSell,
        permissions: [],
      };

      // Snapshot the context the store held BEFORE we resolve /me, so we can detect
      // a context flip (e.g. pre-auth 'BUYER' default → a seller-only company's 'SELLER').
      const previousActiveStatus = get().activeStatus;

      set({
        screen: 'main',
        activeStatus,
        capabilities,
        profile: {
          firstName: first_name || '',
          lastName: last_name || '',
          patronymic: '',
          email: email || '',
          phone: phone || '',
          position: position || '',
          avatarInitials: initials || '??',
          avatarUrl: avatar ?? null,
          // Persist the backend 2FA flag so SecuritySection/TwoFactorAuth renders the
          // disable panel (not "Enable 2FA") after any reload/relogin — without it the
          // field is undefined and a user with 2FA on can never turn it off.
          is_2fa_enabled: authState.user.is_2fa_enabled ?? false,
        },
        company: company ? {
          id: company.id ?? null,
          name: company.name || '',
          inn: company.inn || '',
          country: company.country != null ? String(company.country) : '',
          city: '',
          logoUrl: company.logo ?? null,
          statusEntries,
        } : {
          id: null,
          name: '',
          inn: '',
          country: '',
          city: '',
          logoUrl: null,
          statusEntries: [],
        },
      });

      // ADR-0005 Phase C: if the resolved context differs from what the store held,
      // any cold-load queries that already fired under the old X-Active-Context header
      // (e.g. ['dashboard-stats', period], which is not context-keyed) must refetch under
      // the new one — otherwise the dashboard can render one cycle of wrong-context data.
      // invalidateQueries() refetches (less jarring than clear()). Dynamic import keeps the
      // store free of a static queryClient import cycle (mirrors the authStore import above).
      if (activeStatus !== previousActiveStatus) {
        const { queryClient } = await import('../lib/queryClient');
        queryClient.invalidateQueries();
      }
    }
  },

  setActiveStatus: (status) => set({ activeStatus: status }),
  updateProfile: (partial) =>
    set((s) => ({ profile: { ...s.profile, ...partial } })),
  updateCompany: (partial) =>
    set((s) => ({ company: { ...s.company, ...partial } })),
}));

/**
 * Derived, purely ADDITIVE selector — it only READS `company.statusEntries` and never
 * touches `screen` / `activeStatus` / the `loadFromAuth` bootstrap flow, so it cannot
 * affect the ADR-0005 cold-load BUYER context default or WP-4's `screen === 'main'`
 * deep-link signal. Returns true iff the current member may act as a SELLER for their
 * company: the company exposes a SELLER context AND the member's `can_sell`
 * capability was not revoked — both already encoded into `statusEntries` by
 * `loadFromAuth` (rawEntries from `company_types`, filtered by `can_sell`/`can_buy`).
 * Mirrors the sell-capability derivation already used in App.tsx / AppShell.tsx.
 *
 * The Dashboard consumes this to give seller-capable (incl. dual buyer+seller)
 * companies a seller-aware landing instead of the buyer onboarding, WITHOUT flipping
 * the global BUYER `activeStatus` default (that would break the X-Active-Context header
 * and the ADR-0005 cache invalidation).
 */
export const selectIsSellerCapable = (state: { company: Company }): boolean =>
  state.company.statusEntries.some((entry) => entry.status === 'SELLER');
