/**
 * Журнал печатает подпись, подобранную по КОДУ, а не имя, замороженное при записи события.
 *
 * Событие пишется в момент действия, а читают его позже и на другом языке. Пока сервер клал
 * в `event_params` отображаемое имя, оно замерзало на языке действовавшего: в английской
 * ленте оператора стояло «Deal #16: Черновик → Открытый RFQ» и «Step approved (Руководитель)»
 * (проход глазами 03-08). Канон — ARCH-05 «по проводам коды, слова на краях».
 *
 * Тест берёт НАСТОЯЩИЕ словари: если подпись к коду забыли завести, он падает здесь, а не
 * всплывает кириллицей в английском интерфейсе.
 */

import { describe, it, expect, beforeAll } from 'vitest';
import i18next, { type i18n as I18nType } from 'i18next';

import { activityDetail, activityTitle } from '../activityText';
import { notificationMessage } from '../notificationText';
import en from '../../i18n/locales/en.json';
import ru from '../../i18n/locales/ru.json';

let i18n: I18nType;

beforeAll(async () => {
  i18n = i18next.createInstance();
  await i18n.init({
    lng: 'en-US',
    fallbackLng: 'ru',
    supportedLngs: ['ru', 'en'],
    nonExplicitSupportedLngs: true,
    resources: { en: { translation: en }, ru: { translation: ru } },
    interpolation: { escapeValue: false },
  });
});

const t = () => i18n.t.bind(i18n);

describe('кодовые параметры журнала', () => {
  it('стадии сделки печатаются по коду, а не именем справочника', () => {
    const entry = {
      event_code: 'deal.stage_changed',
      event_params: {
        deal_id: 16,
        from_stage: 'Черновик',
        to_stage: 'Открытый RFQ',
        from_stage_code: 'DRAFT',
        to_stage_code: 'RFQ_OPEN',
      },
      action: 'Стадия изменена',
      detail: 'Сделка #16: Черновик → Открытый RFQ',
    };

    expect(activityDetail(t(), i18n, entry)).toBe('Deal #16: Draft → RFQ open');
  });

  it('роль в цепочке согласования печатается по коду', () => {
    const entry = {
      event_code: 'quote.approval_step_approved',
      event_params: { participation: 'Руководитель', participation_code: 'HEAD' },
      action: 'Шаг согласования пройден',
      detail: 'Шаг согласован (Руководитель)',
    };

    expect(activityDetail(t(), i18n, entry)).toBe('Step approved (Head of unit)');
  });

  it('уровни KYC печатаются по коду', () => {
    const entry = {
      event_code: 'company.kyc_verified',
      event_params: {
        company_name: 'UTY',
        from_status: 'Не верифицирован',
        to_status: 'KYC подтверждён (L2)',
        from_status_code: 'L1_UNVERIFIED',
        to_status_code: 'L2_VERIFIED',
      },
      action: 'KYC: подтверждение',
      detail: 'UTY: Не верифицирован → KYC подтверждён (L2)',
    };

    expect(activityDetail(t(), i18n, entry)).toBe('UTY: Unverified → KYC verified (L2)');
  });

  it('роль компании печатается по коду и в заголовке, и в подробностях', () => {
    const approved = {
      event_code: 'company.role_application_approved',
      event_params: { company_name: 'UTY', role_name: 'Поставщик', role_code: 'SUPPLIER' },
      action: 'Заявка на роль одобрена',
      detail: 'UTY → Поставщик',
    };
    const added = {
      event_code: 'company.role_added',
      event_params: { role_code: 'SUPPLIER', application_id: 4 },
      action: 'Добавлена роль: SUPPLIER',
      detail: 'Одобрена заявка #4',
    };

    expect(activityDetail(t(), i18n, approved)).toBe('UTY → Supplier');
    expect(activityTitle(t(), i18n, added)).toBe('Role added: Supplier');
  });

  it('статус обращения в поддержку приходил кодом — теперь к нему подбирается подпись', () => {
    const entry = {
      event_code: 'support.ticket_status_changed',
      event_params: { from: 'OPEN', to: 'RESOLVED' },
      action: 'Изменён статус обращения',
      detail: 'OPEN → RESOLVED',
    };

    expect(activityDetail(t(), i18n, entry)).toContain('Resolved');
    expect(activityDetail(t(), i18n, entry)).not.toContain('RESOLVED');
  });

  it('СТАРАЯ строка без кода не ломается — печатается тем, что было записано', () => {
    const legacy = {
      event_code: 'deal.stage_changed',
      event_params: { deal_id: 3, from_stage: 'Черновик', to_stage: 'Открытый RFQ' },
      action: 'Стадия изменена',
      detail: 'Сделка #3: Черновик → Открытый RFQ',
    };

    expect(activityDetail(t(), i18n, legacy)).toBe('Deal #3: Черновик → Открытый RFQ');
  });

  it('пункт договора печатается по коду поля, стандартная редакция — по коду варианта', () => {
    const standard = {
      event_code: 'contract.wording_changed',
      event_params: {
        number: 'CT-1',
        field: 'contract_liability_text',
        variant: '',
        variant_code: 'STANDARD',
      },
      action: 'Формулировка договора изменена',
      detail: 'Договор CT-1: contract_liability_text → стандартная редакция',
    };
    const custom = {
      ...standard,
      event_params: {
        number: 'CT-1',
        field: 'contract_liability_text',
        variant: 'Ответственность 2024',
        variant_code: 'CUSTOM',
      },
    };

    expect(activityDetail(t(), i18n, standard)).toBe('Contract CT-1: Liability → Standard wording');
    // Заголовок варианта — пользовательский текст, он НЕ переводится (граница Stripe).
    expect(activityDetail(t(), i18n, custom)).toBe('Contract CT-1: Liability → Ответственность 2024');
  });

  it('уведомления пользуются той же механикой — и тем же разрешением языка', () => {
    // Лента уведомлений была ВТОРОЙ копией механики: починка регионального тега в журнале её
    // не затронула. Теперь обе ходят в `eventText.ts`, и `en-US` резолвится одинаково.
    const entry = {
      event_code: 'company.kyc_status_changed',
      event_params: { level_code: 'L2_VERIFIED' },
      title: 'Статус верификации обновлён',
      message: 'Статус вашей компании: KYC подтверждён (L2)',
    };

    expect(notificationMessage(t(), i18n, entry)).toBe('Your company status: KYC verified (L2)');
  });

  it('незнакомый код не затирает имя', () => {
    const entry = {
      event_code: 'deal.stage_changed',
      event_params: {
        deal_id: 5,
        from_stage: 'Черновик',
        to_stage: 'Особая стадия',
        from_stage_code: 'DRAFT',
        to_stage_code: 'CUSTOM_STAGE_FROM_UNFOLD',
      },
      action: 'Стадия изменена',
      detail: 'Сделка #5',
    };

    expect(activityDetail(t(), i18n, entry)).toBe('Deal #5: Draft → Особая стадия');
  });
});
