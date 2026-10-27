import { configure, getConfig, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { MOCK_MIN_FILL_SECONDS, mockCrmForm } from '@/mocks/crmForm';
import { portalServer } from '@/mocks/server';
import { renderApp } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

/**
 * «Я новый клиент» (M2-CAB-03): форма → `POST {VITE_CRM_URL}/api/v1/leads/web` (мок CRM — MSW,
 * src/mocks/crmForm.ts). Тексты — настоящий ru.json.
 */
type User = ReturnType<typeof userEvent.setup>;
const RETRY_TIMEOUT = (MOCK_MIN_FILL_SECONDS + 2) * 1000;

async function openForm() {
  const user = userEvent.setup();
  const view = renderApp('/new-client');
  await heading('Я новый клиент');
  // Кнопка активна, когда токен формы получен.
  await waitFor(() => expect(screen.getByRole('button', { name: 'Отправить запрос' })).toBeEnabled());
  return { user, ...view };
}

async function fill(
  user: User,
  { name = 'Алишер', phone = '+998 90 123 45 67', email = '', text = 'Нужна интеграция POS', consent = true } = {},
) {
  if (name) await user.type(screen.getByLabelText('Как к вам обращаться'), name);
  if (phone) await user.type(screen.getByLabelText('Телефон'), phone);
  if (email) await user.type(screen.getByLabelText('E-mail'), email);
  if (text) await user.type(screen.getByLabelText('Что нужно'), text);
  if (consent) await user.click(screen.getByRole('checkbox', { name: /Согласен/ }));
}

function crmFails(reason: string, status = 422, field: string | null = null) {
  portalServer.use(
    http.post('*/api/v1/leads/web', () =>
      HttpResponse.json({ code: status === 429 ? 'rate_limited' : 'validation_failed', message: reason, details: { reason, field } }, { status }),
    ),
  );
}

// Отправка — несколько запросов к моку подряд; под параллельной нагрузкой дольше 1 с по умолчанию.
const defaultTimeout = getConfig().asyncUtilTimeout;
beforeAll(() => configure({ asyncUtilTimeout: 5000 }));
afterAll(() => configure({ asyncUtilTimeout: defaultTimeout }));

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('«Я новый клиент»: форма запроса → лид CRM', () => {
  it('успех: тело по контракту CRM, экран «Спасибо» и «Написать в Telegram» с меткой web', async () => {
    const { user } = await openForm();
    await user.type(screen.getByLabelText('Компания (необязательно)'), 'ООО Рельс');
    await fill(user, { email: 'a@rail.uz' });
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));

    expect(await heading('Спасибо! Запрос отправлен')).toBeInTheDocument();
    expect(screen.getByText(/Менеджер свяжется с вами/)).toBeInTheDocument();
    expect(screen.getByText('Мы отправим подтверждение запроса на a@rail.uz.')).toBeInTheDocument();
    const telegram = screen.getByRole('link', { name: 'Написать в Telegram' });
    expect(telegram).toHaveAttribute('href', 'https://t.me/railtech_test_bot?start=web');

    expect(mockCrmForm().tokenRequests).toBe(1);
    expect(mockCrmForm().submissions).toEqual([
      {
        name: 'Алишер',
        company: 'ООО Рельс',
        phone: '+998 90 123 45 67',
        email: 'a@rail.uz',
        text: 'Нужна интеграция POS',
        language: 'ru',
        consent: true,
        form_token: 'mock-form-1',
        website: null,
      },
    ]);
    await expectNoAxeViolations();
  });

  it('согласие обязательно: без галочки запрос не уходит, поле помечено', async () => {
    const { user } = await openForm();
    await fill(user, { consent: false });
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));

    expect(
      await screen.findByText('Без согласия на обработку персональных данных мы не сможем ответить на запрос.'),
    ).toBeInTheDocument();
    const checkbox = screen.getByRole('checkbox', { name: /Согласен/ });
    expect(checkbox).toHaveAttribute('aria-invalid', 'true');
    expect(checkbox).toHaveFocus();
    expect(mockCrmForm().submissions).toEqual([]);
    await expectNoAxeViolations();

    // Галочка снимает ошибку, и запрос уходит.
    await user.click(checkbox);
    expect(screen.queryByText(/Без согласия/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(await heading('Спасибо! Запрос отправлен')).toBeInTheDocument();
  });

  it('телефон или e-mail — хотя бы одно (проверка до отправки)', async () => {
    const { user } = await openForm();
    await fill(user, { phone: '' });
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(await screen.findByText('Укажите телефон или e-mail — хотя бы одно.')).toBeInTheDocument();
    expect(screen.getByLabelText('Телефон')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('E-mail')).toHaveAttribute('aria-invalid', 'true');
    expect(mockCrmForm().submissions).toEqual([]);
  });

  it('honeypot: скрытое поле заполнил бот — ответ как обычно, CRM отбрасывает (lead_id null)', async () => {
    const { user } = await openForm();
    const trap = screen.getByLabelText('Не заполняйте это поле');
    expect(trap).toHaveAttribute('tabindex', '-1');
    expect(trap.closest('[aria-hidden="true"]')).not.toBeNull();
    await fill(user);
    await user.type(trap, 'http://spam.example');
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));

    expect(await heading('Спасибо! Запрос отправлен')).toBeInTheDocument();
    expect(mockCrmForm().submissions[0].website).toBe('http://spam.example');
  });

  it.each([
    ['form_too_fast', 'Нужна интеграция #fast', 'Форма отправлена слишком быстро — проверьте поля и отправьте ещё раз.'],
    [
      'rate_limited',
      'Нужна интеграция #limit',
      'Слишком много запросов с вашего адреса — попробуйте через час или напишите нам в Telegram.',
    ],
  ])('ошибка CRM %s → текст из словаря, форма остаётся', async (_code, text, message) => {
    const { user } = await openForm();
    await fill(user, { text });
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByLabelText('Как к вам обращаться')).toHaveValue('Алишер');
  });

  it('invalid_phone от CRM помечает поле телефона', async () => {
    const { user } = await openForm();
    await fill(user, { phone: '12345' });
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(
      await screen.findByText('Номер не распознан — укажите его с кодом страны, например +998 90 123 45 67.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Телефон')).toHaveAttribute('aria-invalid', 'true');
    await expectNoAxeViolations();
  });

  it('contact_required и consent_required с сервера — тем же текстом, что и проверка формы', async () => {
    crmFails('contact_required', 422, 'phone');
    const { user } = await openForm();
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(await screen.findByText('Укажите телефон или e-mail — хотя бы одно.')).toBeInTheDocument();

    crmFails('consent_required', 422, 'consent');
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(
      await screen.findByText('Без согласия на обработку персональных данных мы не сможем ответить на запрос.'),
    ).toBeInTheDocument();
  });

  it('неизвестный код CRM — общий текст по статусу, без сырого кода', async () => {
    crmFails('something_new', 422);
    const { user } = await openForm();
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(await screen.findByText('Проверьте поля формы.')).toBeInTheDocument();
  });

  it('form_token_expired: тихо берёт новый токен и повторяет один раз', async () => {
    const { user } = await openForm();
    await fill(user, { text: 'Форма открыта давно #expired' });
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));

    // Повтор ждёт `min_fill_seconds` нового токена (в моке — 1 с).
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Спасибо! Запрос отправлен' }, { timeout: RETRY_TIMEOUT }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Форма устарела/)).not.toBeInTheDocument();
    expect(mockCrmForm().tokenRequests).toBe(2);
    expect(mockCrmForm().submissions.map((body) => body.form_token)).toEqual(['mock-form-1', 'mock-form-2']);
  });

  it('повтор тоже отклонён — второй попытки нет, показывается текст', async () => {
    crmFails('form_token_expired', 422, 'form_token');
    const { user } = await openForm();
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(
      await screen.findByText('Форма устарела — обновите страницу и отправьте запрос ещё раз.', {}, { timeout: RETRY_TIMEOUT }),
    ).toBeInTheDocument();
    expect(mockCrmForm().tokenRequests).toBe(2);
  });

  it('CRM недоступна при открытии — понятный текст, «Повторить», отправка выключена', async () => {
    portalServer.use(http.get('*/api/v1/leads/web/token', () => HttpResponse.error(), { once: true }));
    const user = userEvent.setup();
    renderApp('/new-client');
    expect(
      await screen.findByText('Форма сейчас недоступна. Повторите попытку или напишите нам в Telegram.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отправить запрос' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отправить запрос' })).toBeEnabled());
  });

  it('язык запроса — текущий язык интерфейса', async () => {
    const { user } = await openForm();
    await user.click(screen.getByRole('button', { name: 'English' }));
    await heading('I am a new client');
    await user.type(screen.getByLabelText('Your name'), 'Alisher');
    await user.type(screen.getByLabelText('E-mail'), 'a@rail.uz');
    await user.type(screen.getByLabelText('What do you need'), 'POS');
    await user.click(screen.getByRole('checkbox', { name: /I agree/ }));
    await user.click(screen.getByRole('button', { name: 'Send request' }));
    await heading('Thank you! Your request has been sent');
    expect(mockCrmForm().submissions[0]).toMatchObject({ language: 'en', phone: null, email: 'a@rail.uz' });
  });

  it('адрес CRM не задан в сборке — вместо формы «Написать в Telegram»', async () => {
    vi.stubEnv('VITE_CRM_URL', '');
    vi.stubEnv('DEV', false);
    renderApp('/new-client');
    await heading('Я новый клиент');
    expect(screen.getByText('Форма запроса недоступна')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отправить запрос' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Написать в Telegram' })).toHaveAttribute(
      'href',
      'https://t.me/railtech_test_bot?start=web',
    );
    expect(mockCrmForm().tokenRequests).toBe(0);
    await expectNoAxeViolations();
  });
});
