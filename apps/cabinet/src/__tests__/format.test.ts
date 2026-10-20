import type { Invoice } from '@/api/portal';
import { validateInvite, companyChanges } from '@/lib/company';
import {
  amountToCents,
  businessToday,
  centsToAmount,
  daysBetween,
  formatDate,
  formatDateTime,
  formatDecimal,
  formatFileSize,
  formatMoney,
  formatQuantity,
  subtractMoney,
  sumByCurrency,
} from '@/lib/format';
import { invoiceView } from '@/lib/invoice';
import { normalizeAcceptCode, quoteAwaitsDecision, quoteExpired } from '@/lib/quotes';
import { normalizeQuantity } from '@/lib/requests';
import { statusCodes, STATUS_ENTITIES, statusLabelKey } from '@/lib/status';
import i18n from '@/i18n';
import * as fixtures from '@/mocks/fixtures';

/** Пробелы-разделители `Intl` (U+00A0, U+202F) → обычный пробел: кейсы читаются глазами. */
const plain = (text: string) => text.replace(/[\u00a0\u202f]/g, " ");
const NOW = Date.parse('2026-10-14T12:00:00+05:00');

describe('formatMoney — строка API + валюта → формат по локали', () => {
  it.each([
    ['ru', { amount: '48600000.00', currency: 'UZS' }, '48 600 000 UZS'],
    ['ru', { amount: '18750000.50', currency: 'UZS' }, '18 750 000,50 UZS'],
    ['ru', { amount: '1234.05', currency: 'USD' }, '1 234,05 $'],
    ['ru', { amount: '-500.00', currency: 'UZS' }, '-500 UZS'],
    ['ru', { amount: '0.00', currency: 'UZS' }, '0 UZS'],
    ['uz', { amount: '48600000.00', currency: 'UZS' }, '48 600 000 soʻm'],
    ['uz', { amount: '12500.00', currency: 'USD' }, '12 500 US$'],
    ['en', { amount: '48600000.00', currency: 'UZS' }, 'UZS 48,600,000'],
    ['en', { amount: '1234.50', currency: 'USD' }, '$1,234.50'],
    // Точность больших сумм: строка уходит в Intl без потери копеек.
    ['ru', { amount: '90071992547409.99', currency: 'UZS' }, '90 071 992 547 409,99 UZS'],
  ] as const)('%s %j → %s', (language, money, expected) => {
    expect(plain(formatMoney(money, language))).toBe(expected);
  });

  it.each([
    [null, '—'],
    [undefined, '—'],
    [{ amount: '12', currency: 'UZS' }, '—'],
    [{ amount: '12.5', currency: 'UZS' }, '—'],
  ])('не сумма %j → прочерк', (money, expected) => {
    expect(formatMoney(money, 'ru')).toBe(expected);
  });

  it('неизвестный код валюты — число и код как есть', () => {
    expect(plain(formatMoney({ amount: '10.00', currency: 'ZZ1' }, 'ru'))).toBe('10 ZZ1');
  });

  it('без явного языка — язык интерфейса', async () => {
    await i18n.changeLanguage('en');
    expect(formatMoney({ amount: '1000.00', currency: 'USD' })).toBe('$1,000');
    await i18n.changeLanguage('ru');
  });
});

describe('даты — ISO → Asia/Tashkent, локаль интерфейса', () => {
  it.each([
    // date-time: момент переводится в Ташкент (UTC+5) — 23:30 UTC 8-го это 9-е.
    ['ru', '2026-10-08T23:30:00Z', '9 окт. 2026 г., 04:30'],
    ['ru', '2026-10-08T14:00:00+05:00', '8 окт. 2026 г., 14:00'],
    ['en', '2026-10-08T14:00:00+05:00', 'Oct 8, 2026, 14:00'],
    ['uz', '2026-10-08T14:00:00+05:00', '8-okt, 2026, 14:00'],
  ] as const)('formatDateTime %s %s → %s', (language, value, expected) => {
    expect(plain(formatDateTime(value, language))).toBe(expected);
  });

  it.each([
    // date (календарный день): без сдвига по поясу браузера и Ташкента.
    ['ru', '2026-10-25', '25 окт. 2026 г.'],
    ['ru', '2026-01-01', '1 янв. 2026 г.'],
    ['en', '2026-10-25', 'Oct 25, 2026'],
    ['uz', '2026-10-25', '25-okt, 2026'],
    ['ru', '2026-10-08T23:30:00Z', '9 окт. 2026 г.'],
  ] as const)('formatDate %s %s → %s', (language, value, expected) => {
    expect(plain(formatDate(value, language))).toBe(expected);
  });

  it.each([null, undefined, '', 'не дата'])('пустое или битое %j → прочерк', (value) => {
    expect(formatDate(value, 'ru')).toBe('—');
    expect(formatDateTime(value, 'ru')).toBe('—');
  });

  it.each([
    ['2026-10-14T12:00:00+05:00', '2026-10-14'],
    // 20:00 UTC 13-го — в Ташкенте уже 14-е (01:00).
    ['2026-10-13T20:00:00Z', '2026-10-14'],
    ['2026-10-13T18:59:00Z', '2026-10-13'],
  ])('businessToday(%s) = %s', (now, expected) => {
    expect(businessToday(Date.parse(now))).toBe(expected);
  });

  it.each([
    ['2026-10-07', '2026-10-14', 7],
    ['2026-10-14', '2026-10-14', 0],
    ['2026-10-30', '2026-10-14', -16],
    ['2026-02-28', '2026-03-01', 1],
  ])('daysBetween(%s, %s) = %d', (from, to, expected) => {
    expect(daysBetween(from, to)).toBe(expected);
  });
});

describe('числа, количества, размеры', () => {
  it.each([
    ['200', 'шт', 'ru', '200 шт'],
    ['2.5', 'м', 'ru', '2,5 м'],
    ['1500', null, 'en', '1,500'],
    [null, 'шт', 'ru', '—'],
  ] as const)('formatQuantity(%s, %s) %s → %s', (quantity, unit, language, expected) => {
    expect(plain(formatQuantity(quantity, unit, language))).toBe(expected);
  });

  it('formatDecimal: не число — как есть', () => {
    expect(formatDecimal('около 10', 'ru')).toBe('около 10');
  });

  it.each([
    [512, 'ru', '512 Б'],
    [184320, 'ru', '180 кБ'],
    [1572864, 'ru', '1,5 МБ'],
    [184320, 'en', '180 kB'],
    [null, 'ru', '—'],
  ] as const)('formatFileSize(%s) %s → %s', (bytes, language, expected) => {
    expect(plain(formatFileSize(bytes, language))).toBe(expected);
  });
});

describe('суммы без плавающей точки', () => {
  it.each([
    ['13750000.50', 1375000050n],
    ['-0.01', -1n],
    ['0.00', 0n],
  ])('amountToCents(%s) = %s', (amount, cents) => {
    expect(amountToCents(amount)).toBe(cents);
    expect(centsToAmount(cents)).toBe(amount);
  });

  it('разность и суммы по валютам', () => {
    expect(subtractMoney({ amount: '27500000.00', currency: 'UZS' }, { amount: '13750000.10', currency: 'UZS' })).toEqual({
      amount: '13749999.90',
      currency: 'UZS',
    });
    expect(subtractMoney({ amount: '1.00', currency: 'UZS' }, { amount: '1.00', currency: 'USD' })).toBeNull();
    expect(
      sumByCurrency([
        { amount: '10.50', currency: 'UZS' },
        { amount: '5.00', currency: 'USD' },
        { amount: '2.55', currency: 'UZS' },
      ]),
    ).toEqual([
      { amount: '13.05', currency: 'UZS' },
      { amount: '5.00', currency: 'USD' },
    ]);
  });
});

describe('просрочка счёта вычисляется из due_date', () => {
  const base: Invoice = {
    id: 1,
    deal: { id: 1, number: 'D-1', title: null },
    number: 'S-1',
    status: 'issued',
    total: { amount: '100.00', currency: 'UZS' },
    paid: { amount: '0.00', currency: 'UZS' },
    due_date: '2026-10-14',
  };
  it.each([
    ['срок сегодня — не просрочен', {}, null, 'issued'],
    ['срок вчера — 1 день', { due_date: '2026-10-13' }, 1, 'overdue'],
    ['частично оплачен, срок прошёл', { status: 'partially_paid', due_date: '2026-10-07', paid: { amount: '40.00', currency: 'UZS' } }, 7, 'overdue'],
    ['оплачен — не просрочен', { status: 'paid', due_date: '2026-09-01', paid: { amount: '100.00', currency: 'UZS' } }, null, 'paid'],
    ['отменён — не просрочен', { status: 'cancelled', due_date: '2026-09-01' }, null, 'cancelled'],
    ['остаток 0 при статусе issued — не просрочен', { due_date: '2026-09-01', paid: { amount: '100.00', currency: 'UZS' } }, null, 'issued'],
    ['ERP уже поставил overdue', { status: 'overdue', due_date: '2026-10-14' }, 1, 'overdue'],
  ] as const)('%s', (_name, patch, days, status) => {
    const view = invoiceView({ ...base, ...patch } as Invoice, NOW);
    expect(view.overdueDays).toBe(days);
    expect(view.displayStatus).toBe(status);
  });
});

describe('КП: срок действия и код акцепта', () => {
  it.each([
    [{ status: 'sent', valid_until: '2026-10-25' }, false, true],
    [{ status: 'viewed', valid_until: '2026-10-14' }, false, true],
    [{ status: 'sent', valid_until: '2026-10-13' }, true, false],
    [{ status: 'expired', valid_until: '2026-10-25' }, true, false],
    [{ status: 'accepted', valid_until: '2026-10-01' }, false, false],
    [{ status: 'sent', valid_until: null }, false, true],
  ] as const)('%j → истекло %s, ждёт решения %s', (quote, expired, awaiting) => {
    expect(quoteExpired(quote, NOW)).toBe(expired);
    expect(quoteAwaitsDecision(quote, NOW)).toBe(awaiting);
  });

  it('код акцепта из сообщения — без пробелов', () => {
    expect(normalizeAcceptCode(' 24 68 ')).toBe('2468');
  });
});

describe('строки запроса: количество', () => {
  it.each([
    ['12', '12'],
    ['2,5', '2.5'],
    [' 1 000 ', '1000'],
    ['0', null],
    ['-1', null],
    ['abc', null],
    ['1.2.3', null],
  ])('normalizeQuantity(%j) = %j', (value, expected) => {
    expect(normalizeQuantity(value)).toBe(expected);
  });
});

describe('компания и приглашение', () => {
  it('в PUT уходят только изменённые поля', () => {
    expect(
      companyChanges(fixtures.company, {
        name: fixtures.company.name,
        inn: fixtures.company.inn ?? '',
        legal_address: ' Новый адрес ',
        bank_details: fixtures.company.bank_details ?? '',
        language: 'uz',
      }),
    ).toEqual({ legal_address: 'Новый адрес', language: 'uz' });
  });

  const draft = { name: 'Тест', email: '', phone: '', language: 'ru' as const, can_act: false, channels: { email: true, telegram: false } };
  it.each([
    ['без имени и e-mail', { name: ' ' }, ['name', 'email']],
    ['без каналов', { email: 'a@b.uz', channels: { email: false, telegram: false } }, ['channels']],
    ['Telegram без телефона', { email: 'a@b.uz', channels: { email: true, telegram: true } }, ['phone']],
    ['битый e-mail', { email: 'a@b' }, ['email']],
  ] as const)('%s → %j', (_name, patch, problems) => {
    const result = validateInvite({ ...draft, ...patch });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.problems).toEqual(problems);
  });

  it('корректное приглашение — тело по контракту TeamInvite', () => {
    expect(validateInvite({ ...draft, email: ' a@b.uz ', phone: '+998 90 123 45 67', channels: { email: true, telegram: true } })).toEqual({
      ok: true,
      body: { name: 'Тест', email: 'a@b.uz', phone: '+998 90 123 45 67', language: 'ru', can_act: false, channels: ['email', 'telegram'] },
    });
  });
});

describe('статусы: подпись есть для каждого кода во всех словарях', () => {
  for (const language of ['ru', 'uz', 'en']) {
    it(language, () => {
      for (const entity of STATUS_ENTITIES) {
        for (const code of statusCodes(entity)) {
          const key = statusLabelKey(entity, code as never);
          expect(i18n.exists(key, { lng: language }), `${language}: ${key}`).toBe(true);
        }
      }
    });
  }
});
