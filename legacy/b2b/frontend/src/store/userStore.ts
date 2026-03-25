import { create } from 'zustand';

/* ─── Company Status (what the company does on the platform) ────────── */
export type CompanyStatus = 'BUYER' | 'MANUFACTURER' | 'SELLER';

export const companyStatusLabels: Record<CompanyStatus, string> = {
  BUYER: 'Покупатель',
  MANUFACTURER: 'Производитель',
  SELLER: 'Продавец',
};

export const companyStatusDescriptions: Record<CompanyStatus, string> = {
  BUYER: 'Только запрашивает КП и закупает оборудование',
  MANUFACTURER: 'Производит, продаёт напрямую или через продавцов, может закупать',
  SELLER: 'Посредник: покупает и перепродаёт, может добавлять товары в наличии',
};

/* ─── Verification status per company status ────────────────────────── */
export type VerificationStatus = 'pending' | 'verified' | 'rejected';

export const verificationLabels: Record<VerificationStatus, string> = {
  pending: 'Ожидает подтверждения',
  verified: 'Подтверждён',
  rejected: 'Отклонён',
};

export interface CompanyStatusEntry {
  status: CompanyStatus;
  verification: VerificationStatus;
  /** For SELLER: manufacturer must confirm the seller relationship */
  manufacturerConfirmation?: 'pending' | 'confirmed' | 'rejected';
}

/* ─── User Role (exactly ONE per employee, assigned by company admin) ── */
export type UserRole = 'ADMIN' | 'MANAGER' | 'EMPLOYEE';

export const roleLabels: Record<UserRole, string> = {
  ADMIN: 'Администратор',
  MANAGER: 'Менеджер',
  EMPLOYEE: 'Сотрудник',
};

export const roleDescriptions: Record<UserRole, string> = {
  ADMIN: 'Полный доступ, управление пользователями и делегирование прав',
  MANAGER: 'Основные бизнес-операции: сделки, закупки, котировки',
  EMPLOYEE: 'Ограниченный доступ на просмотр или определённые операции',
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
}

/* ─── Company ───────────────────────────────────────────────────────── */
export interface Company {
  name: string;
  inn: string;
  kycStatus: 'verified' | 'pending' | 'not_started';
  country: string;
  city: string;
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

  /* ── Auth integration ── */
  loadFromAuth: () => Promise<void>;

  /* ── Onboarding actions ── */
  completeOnboarding: (data: {
    email: string;
    companyName: string;
    companyInn: string;
    selectedStatus: CompanyStatus;
    firstName: string;
    lastName: string;
  }) => void;

  /* ── Admin approval simulation ── */
  adminApproveStatus: (status: CompanyStatus) => void;
  adminRejectStatus: (status: CompanyStatus) => void;

  /* ── Manufacturer confirms seller ── */
  manufacturerConfirmSeller: (status: CompanyStatus) => void;

  /* ── Add additional status (company already verified) ── */
  addCompanyStatus: (status: CompanyStatus) => void;

  /* ── Navigation ── */
  setActiveStatus: (status: CompanyStatus) => void;
  setRole: (role: UserRole) => void;
  updateProfile: (profile: Partial<UserProfile>) => void;
  enterMainApp: () => void;
  resetToOnboarding: () => void;
}

/* ─── Helpers ──────────────────────────────────────────────────────── */

function getVerifiedStatuses(entries: CompanyStatusEntry[]): CompanyStatus[] {
  return entries.filter((e) => e.verification === 'verified').map((e) => e.status);
}

/* ─── Store ─────────────────────────────────────────────────────────── */

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const useUserStore = create<UserState>((set, _get) => ({
  /* Default: empty until loaded from auth */
  screen: 'onboarding',
  role: 'ADMIN',
  activeStatus: 'SELLER',
  profile: {
    firstName: '',
    lastName: '',
    patronymic: '',
    email: '',
    phone: '',
    position: '',
    avatarInitials: '',
  },
  company: {
    name: '',
    inn: '',
    kycStatus: 'not_started',
    country: '',
    city: '',
    statusEntries: [],
  },

  loadFromAuth: async () => {
    // Dynamic import to avoid circular dependency
    const { useAuthStore: authStoreHook } = await import('../store/authStore');
    const authState = authStoreHook.getState();
    if (authState.user) {
      const { first_name, last_name, email, role_code, company } = authState.user;
      const initials = `${(first_name || '')[0] || ''}${(last_name || '')[0] || ''}`.toUpperCase();
      set({
        screen: 'main',
        role: (role_code === 'ADMIN' || role_code === 'SALES_MANAGER') ? 'ADMIN' :
              role_code === 'ACCOUNT_MANAGER' ? 'MANAGER' : 'EMPLOYEE',
        profile: {
          firstName: first_name || '',
          lastName: last_name || '',
          patronymic: '',
          email: email || '',
          phone: '',
          position: '',
          avatarInitials: initials || '??',
        },
        company: company ? {
          name: company.name || '',
          inn: company.inn || '',
          kycStatus: (company.verification_status === 'verified' ? 'verified' : 'pending') as 'verified' | 'pending' | 'not_started',
          country: company.country || '',
          city: '',
          statusEntries: [],
        } : {
          name: '',
          inn: '',
          kycStatus: 'not_started',
          country: '',
          city: '',
          statusEntries: [],
        },
      });
    }
  },

  completeOnboarding: (data) => {
    const initials = `${data.firstName[0] ?? ''}${data.lastName[0] ?? ''}`.toUpperCase();
    set({
      screen: 'pending_verification',
      role: 'ADMIN', // First user is always admin
      activeStatus: data.selectedStatus,
      profile: {
        firstName: data.firstName,
        lastName: data.lastName,
        patronymic: '',
        email: data.email,
        phone: '',
        position: '',
        avatarInitials: initials,
      },
      company: {
        name: data.companyName,
        inn: data.companyInn,
        kycStatus: 'pending',
        country: 'Узбекистан',
        city: 'Ташкент',
        statusEntries: [
          { status: data.selectedStatus, verification: 'pending' },
        ],
      },
    });
  },

  adminApproveStatus: (status) =>
    set((s) => {
      const entries = s.company.statusEntries.map((e) =>
        e.status === status ? { ...e, verification: 'verified' as const } : e
      );
      const hasVerified = entries.some((e) => e.verification === 'verified');
      return {
        company: { ...s.company, statusEntries: entries, kycStatus: hasVerified ? 'verified' : s.company.kycStatus },
        screen: hasVerified ? 'main' : s.screen,
      };
    }),

  adminRejectStatus: (status) =>
    set((s) => ({
      company: {
        ...s.company,
        statusEntries: s.company.statusEntries.map((e) =>
          e.status === status ? { ...e, verification: 'rejected' as const } : e
        ),
      },
    })),

  manufacturerConfirmSeller: (status) =>
    set((s) => ({
      company: {
        ...s.company,
        statusEntries: s.company.statusEntries.map((e) =>
          e.status === status ? { ...e, manufacturerConfirmation: 'confirmed' as const } : e
        ),
      },
    })),

  addCompanyStatus: (status) =>
    set((s) => {
      const exists = s.company.statusEntries.some((e) => e.status === status);
      if (exists) return {};
      return {
        company: {
          ...s.company,
          statusEntries: [
            ...s.company.statusEntries,
            {
              status,
              verification: 'pending',
              ...(status === 'SELLER' ? { manufacturerConfirmation: 'pending' as const } : {}),
            },
          ],
        },
      };
    }),

  setActiveStatus: (status) => set({ activeStatus: status }),
  setRole: (role) => set({ role }),
  updateProfile: (partial) =>
    set((s) => ({ profile: { ...s.profile, ...partial } })),
  enterMainApp: () => set({ screen: 'main' }),
  resetToOnboarding: () =>
    set({
      screen: 'onboarding',
      company: {
        name: '',
        inn: '',
        kycStatus: 'not_started',
        country: '',
        city: '',
        statusEntries: [],
      },
    }),
}));

/* ─── Selectors ────────────────────────────────────────────────────── */

export function useVerifiedStatuses(): CompanyStatus[] {
  const entries = useUserStore((s) => s.company.statusEntries);
  return getVerifiedStatuses(entries);
}

export function useIsStatusVerified(status: CompanyStatus): boolean {
  const entries = useUserStore((s) => s.company.statusEntries);
  return entries.some((e) => e.status === status && e.verification === 'verified');
}
