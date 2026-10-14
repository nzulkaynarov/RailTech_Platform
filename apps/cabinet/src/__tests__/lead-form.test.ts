import { CrmFormError, type WebFormToken, type WebLeadIn } from '@/api/crm';
import { EMPTY_LEAD_FORM, submitWithFreshToken, toWebLead, validateLeadForm, type LeadFormValues } from '@/lib/leadForm';

/** Форма «Я новый клиент» без React: проверка, тело для CRM, повтор с новым токеном (M2-CAB-03). */
const filled: LeadFormValues = {
  ...EMPTY_LEAD_FORM,
  name: '  Алишер ',
  phone: '+998 90 123 45 67',
  text: ' Нужна интеграция ',
  consent: true,
};

function token(value: string, minFill = 3): WebFormToken {
  return { token: value, expires_at: '2026-10-14T13:00:00Z', min_fill_seconds: minFill };
}

describe('validateLeadForm', () => {
  it.each<[Partial<LeadFormValues>, string, string | null]>([
    [{ name: ' ' }, 'name_required', 'name'],
    [{ phone: '', email: '' }, 'contact_required', 'phone'],
    [{ phone: '', email: 'not-an-email' }, 'invalid_email', 'email'],
    [{ text: '   ' }, 'text_required', 'text'],
    [{ consent: false }, 'consent_required', 'consent'],
  ])('%o → %s', (patch, code, field) => {
    expect(validateLeadForm({ ...filled, ...patch })).toEqual({ code, field });
  });

  it('достаточно одного контакта', () => {
    expect(validateLeadForm(filled)).toBeNull();
    expect(validateLeadForm({ ...filled, phone: '', email: 'a@rail.uz' })).toBeNull();
  });
});

describe('toWebLead', () => {
  it('обрезает пробелы, пустое — null, язык — код контракта, согласие и honeypot как есть', () => {
    expect(toWebLead({ ...filled, company: ' ', website: '' }, 'uz-Latn-UZ', 't1')).toEqual<WebLeadIn>({
      name: 'Алишер',
      company: null,
      phone: '+998 90 123 45 67',
      email: null,
      text: 'Нужна интеграция',
      language: 'uz',
      consent: true,
      form_token: 't1',
      website: null,
    });
    expect(toWebLead(filled, 'de', 't1').language).toBe('ru');
    expect(toWebLead({ ...filled, website: 'http://spam' }, 'en', 't1').website).toBe('http://spam');
  });
});

describe('submitWithFreshToken', () => {
  const build = (formToken: string) => toWebLead(filled, 'ru', formToken);

  it('успех с первого раза — токен не перезапрашивается', async () => {
    const submit = vi.fn().mockResolvedValue({ lead_id: 7 });
    const refreshToken = vi.fn();
    await expect(submitWithFreshToken({ build, token: token('t1'), refreshToken, submit })).resolves.toEqual({ lead_id: 7 });
    expect(refreshToken).not.toHaveBeenCalled();
  });

  it.each(['form_token_expired', 'form_token_invalid'])(
    '%s → новый токен, пауза min_fill_seconds, один повтор',
    async (code) => {
      const submit = vi
        .fn()
        .mockRejectedValueOnce(new CrmFormError(422, code, 'form_token'))
        .mockResolvedValueOnce({ lead_id: 8 });
      const refreshToken = vi.fn().mockResolvedValue(token('t2', 3));
      const wait = vi.fn().mockResolvedValue(undefined);

      await expect(submitWithFreshToken({ build, token: token('t1'), refreshToken, submit, wait })).resolves.toEqual({
        lead_id: 8,
      });
      expect(submit.mock.calls.map(([body]) => (body as WebLeadIn).form_token)).toEqual(['t1', 't2']);
      // Без паузы CRM ответила бы form_too_fast: токен только что выдан.
      expect(wait).toHaveBeenCalledWith(3250);
    },
  );

  it('повтор отклонён — ошибка наружу, третьей попытки нет', async () => {
    const expired = new CrmFormError(422, 'form_token_expired', 'form_token');
    const submit = vi.fn().mockRejectedValue(expired);
    const refreshToken = vi.fn().mockResolvedValue(token('t2', 0));
    await expect(
      submitWithFreshToken({ build, token: token('t1'), refreshToken, submit, wait: () => Promise.resolve() }),
    ).rejects.toBe(expired);
    expect(submit).toHaveBeenCalledTimes(2);
    expect(refreshToken).toHaveBeenCalledTimes(1);
  });

  it.each(['form_too_fast', 'rate_limited', 'consent_required', 'network'])('%s — без повтора', async (code) => {
    const failure = new CrmFormError(code === 'rate_limited' ? 429 : 422, code);
    const submit = vi.fn().mockRejectedValue(failure);
    const refreshToken = vi.fn();
    await expect(submitWithFreshToken({ build, token: token('t1'), refreshToken, submit })).rejects.toBe(failure);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(refreshToken).not.toHaveBeenCalled();
  });
});
