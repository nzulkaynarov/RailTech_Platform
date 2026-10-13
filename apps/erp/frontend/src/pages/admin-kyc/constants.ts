import type { Company } from '@/api/accountsApi';

export type KYCCode = 'L1_UNVERIFIED' | 'PROFILE_SUBMITTED' | 'L2_VERIFIED' | 'L3_CONTRACTED';

export const STORAGE_KEY = 'adminKyc';

export const STATUS_BADGE_MAP: Record<
  string,
  { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }
> = {
  L1_UNVERIFIED: { variant: 'secondary', label: 'kycManager.status.P_PENDING' },
  PROFILE_SUBMITTED: { variant: 'outline', label: 'kycManager.status.P_SUBMITTED' },
  L2_VERIFIED: { variant: 'default', label: 'kycManager.status.V_VERIFIED_L2' },
  L3_CONTRACTED: { variant: 'default', label: 'kycManager.status.V_PARTNER_L3' },
};

export const DOC_TYPE_OPTIONS = [
  { value: 'CHARTER', labelKey: 'kycManager.docTypes.charter' },
  { value: 'LICENSE', labelKey: 'kycManager.docTypes.license' },
  { value: 'PASSPORT', labelKey: 'kycManager.docTypes.passport' },
  { value: 'TAX_CERT', labelKey: 'kycManager.docTypes.taxCert' },
  { value: 'OTHER', labelKey: 'kycManager.docTypes.other' },
];

export function getStatusCode(company: Company): string {
  return (company.verification_status_code || String(company.verification_status)) as string;
}
