import type { Company } from '@/api/accountsApi';

/**
 * Чего не хватает, чтобы считать KYC подтверждённым по доказательствам.
 *
 * Признак ЗЕРКАЛИТ серверный `accounts.services.kyc.kyc_evidence_gaps` и возвращает те же
 * коды, а не готовый текст: подпись подбирает витрина (Rule 5). Живёт отдельным файлом, а не
 * внутри страницы, потому что по нему судят ТРИ диалога — карточка компании, меню строки и
 * массовое действие. До 24-08 копия была одна, в карточке, и остальные два пути выдавали
 * уровень без обоснования (находки прогона 20-08 №11 и №12).
 */
export type EvidenceGap = 'NO_DOCUMENTS' | 'NO_INN';

export const EVIDENCE_GAP_LABEL: Record<EvidenceGap, string> = {
  NO_DOCUMENTS: 'kycManager.gapNoDocs',
  NO_INN: 'kycManager.gapNoInn',
};

export function evidenceGapsFor(company: Company): EvidenceGap[] {
  const gaps: EvidenceGap[] = [];
  if ((company.kyc_documents?.length || 0) === 0) gaps.push('NO_DOCUMENTS');
  if (!String(company.inn || '').trim()) gaps.push('NO_INN');
  return gaps;
}

export function companiesMissingEvidence(companies: Company[]): Company[] {
  return companies.filter((company) => evidenceGapsFor(company).length > 0);
}
