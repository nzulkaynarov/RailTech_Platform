import type { User as UserType } from '@/api/accountsApi';

export type Draft = Partial<UserType>;

/** Sentinel for "clear operator role" — shadcn Select can't hold an empty value. */
export const NO_OPERATOR_ROLE = 'none';
