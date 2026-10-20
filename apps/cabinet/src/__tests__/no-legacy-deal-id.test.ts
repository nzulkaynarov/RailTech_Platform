/**
 * C-1/Q-16: клиент видит сделку как `deal {id, number, title}`, внутренний `deal_id` — поле, снятое контрактом 0.3.0.
 * Читать его Cabinet не должен нигде. Исключения: сгенерированные типы, фильтр `GET /documents?deal_id=`
 * (параметр запроса, не поле ответа) и фильтр в моке.
 */
const ALLOWED = new Set([
  'api/portal.d.ts',
  'api/crm-form.d.ts',
  'pages/deal.tsx', // useDocuments({ deal_id }) — фильтр запроса
  'mocks/handlers.ts', // фильтр ?deal_id= в моке GET /documents
]);

const sources = import.meta.glob<string>(['../**/*.{ts,tsx}', '!../__tests__/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
});

describe('устаревший deal_id', () => {
  const files = Object.entries(sources).map(([file, text]) => [file.replace(/^\.\.\//, ''), text] as const);

  it('исходники найдены', () => {
    expect(files.length).toBeGreaterThan(50);
    expect(files.some(([file]) => file === 'pages/deal.tsx')).toBe(true);
  });

  it('не встречается нигде в src, кроме типов и фильтра запроса', () => {
    const offenders = files.filter(([file, text]) => !ALLOWED.has(file) && text.includes('deal_id')).map(([file]) => file);
    expect(offenders).toEqual([]);
  });

  it('в deal.tsx — только фильтр документов', () => {
    const text = files.find(([file]) => file === 'pages/deal.tsx')?.[1] ?? '';
    const lines = text
      .split('\n')
      .filter((line) => line.includes('deal_id') && !line.trim().startsWith('*') && !line.trim().startsWith('//'));
    expect(lines).toEqual(['  const documents = useDocuments({ deal_id: dealId });']);
  });
});
