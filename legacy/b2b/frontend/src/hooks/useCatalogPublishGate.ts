import { useUserStore } from '@/store/userStore';
import { isKycVerified } from '@/config/navigation';

/** Почему продавец пока не может опубликовать карточку. */
export type CatalogPublishBlockReason = 'kyc';

export interface CatalogPublishGate {
  /** Зритель работает на стороне продавца — только он публикует карточки. */
  isSeller: boolean;
  /** Публиковать нельзя: действует порог верификации. */
  blocked: boolean;
  reason: CatalogPublishBlockReason | null;
  /** Код ошибки, который вернул бы бэкенд, — для переиспользования translateApiError(). */
  errorCode: string | null;
}

const NOT_BLOCKED: CatalogPublishGate = { isSeller: false, blocked: false, reason: null, errorCode: null };

/**
 * Наполнять каталог можно до верификации, публиковать — нет (эталон Amazon Seller Central:
 * листинги готовятся, пока идёт проверка аккаунта, живыми становятся после неё).
 *
 * Зачем предупреждать заранее, а не ловить 403: продавец заводит десятки карточек и узнавал
 * бы о пороге на последнем шаге — та же «поздняя неожиданность», ради которой сделан
 * `useQuoteSendGate` для отправки КП. Здесь та же механика и тот же источник правды
 * (`/me.capabilities`), поэтому и хук устроен одинаково.
 *
 * Гейт ИНТЕРФЕЙСНЫЙ: авторитетная проверка живёт в `catalog/publishing.py` и возвращает
 * `SELLER_KYC_REQUIRED`.
 */
export function useCatalogPublishGate(): CatalogPublishGate {
  const role = useUserStore((s) => s.role);
  const activeStatus = useUserStore((s) => s.activeStatus);
  const capabilities = useUserStore((s) => s.capabilities);

  // Оператор публикует в порядке модерации, а не от имени компании, — порог к нему не применим.
  const isSeller = role !== 'ADMIN' && activeStatus === 'SELLER';
  if (!isSeller) return NOT_BLOCKED;

  if (!isKycVerified(capabilities.kyc_level)) {
    return { isSeller, blocked: true, reason: 'kyc', errorCode: 'SELLER_KYC_REQUIRED' };
  }
  return { isSeller, blocked: false, reason: null, errorCode: null };
}
