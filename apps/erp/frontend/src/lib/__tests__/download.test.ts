import { describe, it, expect } from 'vitest';

import { withServerExtension } from '../download';

describe('withServerExtension', () => {
  it('имя с расширением не меняется', () => {
    expect(withServerExtension('Паспорт.pdf', 'attachment; filename="abc.docx"')).toBe('Паспорт.pdf');
  });

  it('имя без расширения получает расширение файла из Content-Disposition', () => {
    expect(withServerExtension('Паспорт изделия', 'attachment; filename="0a1b2c.pdf"')).toBe('Паспорт изделия.pdf');
  });

  it('понимает filename* в UTF-8', () => {
    expect(withServerExtension('Сертификат', "attachment; filename*=utf-8''%D0%BA%D0%BF.docx")).toBe('Сертификат.docx');
  });

  it('без заголовка или без расширения у сервера — как было', () => {
    expect(withServerExtension('Паспорт', undefined)).toBe('Паспорт');
    expect(withServerExtension('Паспорт', 'attachment; filename="blob"')).toBe('Паспорт');
  });
});
