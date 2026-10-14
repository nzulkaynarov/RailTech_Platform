import { useUserStore, type Capabilities } from '@/store/userStore';

/** Why the current seller cannot send the КП. Order mirrors the backend send_to_client gates. */
export type QuoteSendBlockReason = 'subscription' | 'demo' | 'disabled_by_operator';

export interface QuoteSendGate {
  /** The viewer is acting on the seller side (the only side that sends a КП). */
  isSeller: boolean;
  /** The seller cannot send the КП yet — an entitlement / demo blocker applies. */
  blocked: boolean;
  reason: QuoteSendBlockReason | null;
  /** The stable API error code the backend would raise, for translateApiError() reuse. */
  errorCode: string | null;
}

const NOT_BLOCKED: QuoteSendGate = { isSeller: false, blocked: false, reason: null, errorCode: null };

/**
 * Чистая часть гейта — отдельно от хука, чтобы её можно было проверить без монтирования
 * компонента и стора. Порядок проверок повторяет `crm.services.quotes.send_to_client`:
 * право на отправку, DEMO — отдельным случаем. Порога верификации компании больше нет
 * (M1-ERP-02): отправку ограничивает право роли и подписка, их держит бэкенд.
 */
export function resolveQuoteSendGate(capabilities: Capabilities, isSeller: boolean): QuoteSendGate {
  if (!isSeller) return NOT_BLOCKED;

  if (capabilities.quote_send_is_demo) {
    return { isSeller, blocked: true, reason: 'demo', errorCode: 'QUOTE_SEND_NOT_ENTITLED' };
  }
  if (!capabilities.can_send_quotes) {
    // Два РАЗНЫХ состояния сваливались в одно. При явном запрете платформы продавцу с
    // ОПЛАЧЕННОЙ подпиской печаталось «требуется активная подписка» и предлагалась кнопка в
    // раздел подписки, где та же подписка написана активной: ложная причина плюс бесполезное
    // действие. Само правило не меняется — запрет платформы побеждает подписку (ADR-0006);
    // меняется то, как о нём сообщают.
    if (capabilities.quote_send_blocked_by_operator) {
      return { isSeller, blocked: true, reason: 'disabled_by_operator', errorCode: 'QUOTE_SEND_NOT_ENTITLED' };
    }
    return { isSeller, blocked: true, reason: 'subscription', errorCode: 'QUOTE_SEND_NOT_ENTITLED' };
  }
  return { isSeller, blocked: false, reason: null, errorCode: null };
}

/**
 * WP-H — proactive КП send-gate, read from /me.capabilities. Lets the builder surface a
 * subscription/demo blocker BEFORE the seller spends an hour on data entry (the audit's
 * "late surprise" at send). UI-gating only — send_to_client remains the authoritative gate.
 */
export function useQuoteSendGate(): QuoteSendGate {
  const activeStatus = useUserStore((s) => s.activeStatus);
  const capabilities = useUserStore((s) => s.capabilities);

  // Sending is a seller-side action.
  const isSeller = activeStatus === 'SELLER';
  return resolveQuoteSendGate(capabilities, isSeller);
}
