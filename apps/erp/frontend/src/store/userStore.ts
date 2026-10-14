import { create } from 'zustand';
import i18n from '@/i18n';
import { useThemeStore } from './themeStore';

/** Consolidated effective capabilities (mirrors backend MeSerializer.capabilities, ADR-0005).
 * Single source the unified nav engine (config/navigation.tsx) reads to render/gate items. */
export interface Capabilities {
  permissions: string[];
  /** Роли бэк-офиса сотрудника (M1-ERP-05) — подпись в шапке; системные переводятся по `code`. */
  roles?: { code: string; name: string; is_system: boolean }[];
  /** Wave B2 (auto-claim) — в команде один сотрудник с `deal.manage`, «Взять в работу» — шум.
   * Только скрытие кнопки; распределение решает сервер. См. useIsSoloTeam. */
  is_solo_team?: boolean;
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
}

/* ─── App State: 'loading' until loadFromAuth() resolves /me, then 'main' ── */
export type AppScreen = 'loading' | 'main';

/* ─── Store ─────────────────────────────────────────────────────────── */
interface UserState {
  screen: AppScreen;
  profile: UserProfile;
  company: Company;
  /** ADR-0005: consolidated capability object driving the unified nav engine. */
  capabilities: Capabilities;

  /* ── Auth integration ── */
  loadFromAuth: () => Promise<void>;

  updateProfile: (profile: Partial<UserProfile>) => void;
  updateCompany: (company: Partial<Company>) => void;
}

/* ─── Store ─────────────────────────────────────────────────────────── */

export const useUserStore = create<UserState>((set) => ({
  /* Default: empty until loaded from auth. */
  screen: 'loading',
  capabilities: {
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

      // ERP — бэк-офис одной компании: действия ограничивают права ролей из /me (M1-ERP-05);
      // пустой список прав = прав нет (роль «Наблюдатель»): читать можно, действовать — нет.
      const userPayload = authState.user as { capabilities?: Capabilities };
      const capabilities: Capabilities = userPayload.capabilities ?? { permissions: [] };

      set({
        screen: 'main',
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
        } : {
          id: null,
          name: '',
          inn: '',
          country: '',
          city: '',
          logoUrl: null,
        },
      });
    }
  },

  updateProfile: (partial) =>
    set((s) => ({ profile: { ...s.profile, ...partial } })),
  updateCompany: (partial) =>
    set((s) => ({ company: { ...s.company, ...partial } })),
}));
