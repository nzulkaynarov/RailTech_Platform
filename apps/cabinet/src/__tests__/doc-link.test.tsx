import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { setMockLegal } from '@/mocks/handlers';
import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations } from '@/test/screens';

/**
 * ДК-1, ДК-2 · документ по ссылке из письма (`/d/<токен>`): гость видит один документ и ничего от кабинета; отозванная,
 * просроченная и неизвестная ссылки показывают только причину; любое действие — диалог кода на адрес получателя, код — вход:
 * после него действие выполняется само (оферта и политика — между кодом и действием); вошедший контакт кода не видит;
 * права не шире контакта.
 */
const LIVE = 'live-token-0123456789';
const VIEWER = 'viewer-token-0123456789';
const FOREIGN = 'foreign-token-0123456789';
const open = (token = LIVE) => renderApp(`/d/${token}`);
const quoteHeading = () => screen.findByRole('heading', { level: 1, name: 'КП QT-0118' });

describe('документ по ссылке: гость', () => {
  it('видит один документ — состав, факты, «Скачать PDF» — и ни одного раздела кабинета', async () => {
    const seen: string[] = [];
    portalServer.events.on('request:start', ({ request }) => void seen.push(new URL(request.url).pathname));
    open();

    await quoteHeading();
    expect(screen.getByText('ООО «РейлТех»')).toBeInTheDocument();
    expect(screen.getByText('ООО «Восток Транс»')).toBeInTheDocument();
    expect(screen.getAllByText(/с НДС/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Вы смотрите один документ, присланный на p\*\*\*@vostok-trans\.uz/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Скачать PDF: КП QT-0118' })).toBeEnabled();
    expect(screen.getByText(/Любое действие — после кода, который придёт на p\*\*\*@vostok-trans\.uz/)).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Разделы кабинета' })).not.toBeInTheDocument();
    expect(seen.some((path) => /\/(me|quotes|requests|company|contracts)$/.test(path))).toBe(false);
    await expectNoAxeViolations();
  });

  it('PDF скачивается по токену из тела запроса', async () => {
    const user = userEvent.setup();
    const bodies: unknown[] = [];
    portalServer.events.on('request:start', async ({ request }) => {
      if (request.url.endsWith('/doc-links/pdf')) bodies.push(await request.clone().json());
    });
    vi.mocked(window.URL.createObjectURL).mockClear();
    open();
    await quoteHeading();

    await user.click(screen.getByRole('button', { name: 'Скачать PDF: КП QT-0118' }));

    await waitFor(() => expect(window.URL.createObjectURL).toHaveBeenCalledTimes(1));
    expect(bodies).toEqual([{ token: LIVE }]);
  });

  it.each([
    ['revoked-token-0123456789', 'Ссылка отозвана'],
    ['expired-token-0123456789', 'Срок ссылки истёк'],
    ['superseded-token-0123456789', 'Есть новая версия предложения'],
    ['unknown-token-0123456789', 'Ссылка не найдена'],
  ])('%s: только причина, ни документа, ни действий', async (token, title) => {
    open(token);

    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument();
    expect(screen.queryByText('ООО «РейлТех»')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Принять предложение' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Скачать PDF/ })).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('принять: один диалог кода, верный код открывает сессию и принимает КП без повторного нажатия', async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    portalServer.events.on('request:start', ({ request }) => void calls.push(new URL(request.url).pathname.split('/doc-links/')[1] ?? ''));
    open();
    await quoteHeading();

    await user.click(screen.getByRole('button', { name: 'Принять предложение' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });
    expect(await within(dialog).findByText(/Отправили код на p\*\*\*@vostok-trans\.uz\. Он действует 10 минут\./)).toBeInTheDocument();
    // адрес нельзя ввести или изменить
    expect(within(dialog).queryByRole('textbox', { name: /почт|e-?mail|адрес/i })).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /Отправить ещё раз через 0:4\d/ })).toBeDisabled();

    await user.type(within(dialog).getByLabelText('Код из письма'), '000000');
    await user.click(within(dialog).getByRole('button', { name: 'Принять предложение' }));
    expect(await within(dialog).findByText(/Код неверный или устарел/)).toBeInTheDocument();
    expect(calls).not.toContain('act');

    await user.clear(within(dialog).getByLabelText('Код из письма'));
    await user.type(within(dialog).getByLabelText('Код из письма'), '123456');
    await user.click(within(dialog).getByRole('button', { name: 'Принять предложение' }));

    expect(await screen.findByText('Предложение принято. Договор появится в вашем Кабинете.')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // код → вход → действие: ровно по одному запросу, без второго кода
    expect(calls.filter((path) => path === 'code')).toHaveLength(1);
    expect(calls.filter((path) => path === 'verify')).toHaveLength(2);
    expect(calls.filter((path) => path === 'act')).toHaveLength(1);
    expect(screen.getByText(/Вы вошли как/)).toBeInTheDocument();
  });

  it('пять неверных кодов подряд: код больше не действует, нужен новый', async () => {
    const user = userEvent.setup();
    open();
    await quoteHeading();
    await user.click(screen.getByRole('button', { name: 'Принять предложение' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });

    await user.type(await within(dialog).findByLabelText('Код из письма'), '111111');
    await user.click(within(dialog).getByRole('button', { name: 'Принять предложение' }));

    expect(await within(dialog).findByText(/Пять неверных кодов подряд/)).toBeInTheDocument();
  });

  it('вернуть с замечаниями: без текста не уходит; с текстом и кодом — «возвращено»', async () => {
    const user = userEvent.setup();
    open();
    await quoteHeading();
    await user.click(screen.getByRole('button', { name: 'Вернуть с замечаниями' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });

    await user.type(await within(dialog).findByLabelText('Код из письма'), '123456');
    await user.click(within(dialog).getByRole('button', { name: 'Вернуть с замечаниями' }));
    expect(await within(dialog).findByText(/Укажите причину/)).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText('Что нужно исправить?'), 'Срок поставки велик');
    await user.click(within(dialog).getByRole('button', { name: 'Вернуть с замечаниями' }));

    expect(await screen.findByText('Предложение возвращено с замечаниями.')).toBeInTheDocument();
  });

  it('при первом входе между кодом и действием — оферта и политика; после «Принимаю» действие выполняется само', async () => {
    setMockLegal({ published: true, accepted: false });
    const user = userEvent.setup();
    open();
    await quoteHeading();
    await user.click(screen.getByRole('button', { name: 'Принять предложение' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });
    expect(within(dialog).getByText(/примете условия использования и политику/)).toBeInTheDocument();
    await user.type(await within(dialog).findByLabelText('Код из письма'), '123456');
    await user.click(within(dialog).getByRole('button', { name: 'Принять предложение' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Условия работы в кабинете' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Принимаю' }));

    expect(await screen.findByText('Предложение принято. Договор появится в вашем Кабинете.')).toBeInTheDocument();
  });

  it('«Открыть Кабинет»: тот же диалог кода, после него — свой кабинет', async () => {
    const user = userEvent.setup();
    const { router } = open();
    await quoteHeading();

    await user.click(screen.getByRole('button', { name: 'Открыть Кабинет' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });
    await user.type(await within(dialog).findByLabelText('Код из письма'), '123456');
    await user.click(within(dialog).getByRole('button', { name: 'Открыть Кабинет' }));

    await waitFor(() => expect(router.state.location.pathname).not.toMatch(/^\/d\//));
  });

  it('контакт без права решать: кнопки решения неактивны, причина написана рядом', async () => {
    open(VIEWER);
    await quoteHeading();

    for (const name of ['Принять предложение', 'Вернуть с замечаниями', 'Задать вопрос']) {
      expect(screen.getByRole('button', { name })).toBeDisabled();
    }
    expect(screen.getByText(/нет права принимать решения/)).toBeInTheDocument();
    await expectNoAxeViolations();
  });
});

describe('документ по ссылке: вошедший контакт', () => {
  it('код не нужен: вопрос уходит текстом, принять — после подтверждения', async () => {
    signedIn();
    const user = userEvent.setup();
    const calls: string[] = [];
    portalServer.events.on('request:start', ({ request }) => void calls.push(new URL(request.url).pathname.split('/doc-links/')[1] ?? ''));
    open();
    await quoteHeading();
    expect(screen.getByText(/код не нужен/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Задать вопрос' }));
    let dialog = await screen.findByRole('dialog', { name: 'Задать вопрос' });
    expect(within(dialog).queryByLabelText('Код из письма')).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText('Ваш вопрос'), 'Есть ли скидка?');
    await user.click(within(dialog).getByRole('button', { name: 'Задать вопрос' }));
    expect(await screen.findByText('Вопрос отправлен менеджеру')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Принять предложение' }));
    dialog = await screen.findByRole('dialog', { name: 'Принять предложение?' });
    await user.click(within(dialog).getByRole('button', { name: 'Принять предложение' }));

    expect(await screen.findByText('Предложение принято. Договор появится в вашем Кабинете.')).toBeInTheDocument();
    expect(calls).not.toContain('code');
    expect(calls).not.toContain('verify');
  });

  it('сессия другой компании — гостевой вид и «Выйти»: действий нет', async () => {
    signedIn();
    const user = userEvent.setup();
    open(FOREIGN);

    expect(await screen.findByText('Вы вошли в другой Кабинет')).toBeInTheDocument();
    for (const name of ['Принять предложение', 'Вернуть с замечаниями', 'Задать вопрос', 'Открыть Кабинет']) {
      expect(screen.getByRole('button', { name })).toBeDisabled();
    }
    expect(screen.getByRole('button', { name: 'Выйти' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Выйти' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Принять предложение' })).toBeEnabled());
  });

  it('контакт без права действовать (сессия viewer, интерфейс на узбекском): кнопки неактивны с причиной', async () => {
    signedIn('viewer');
    open(VIEWER);

    expect(await screen.findByText(/qaror qabul qilişga huquq yöq/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Taklifni qabul qiliş' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Savol beriş' })).toBeDisabled();
  });
});
