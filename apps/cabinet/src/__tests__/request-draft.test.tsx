import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { loadRequestDraft, requestDraftKey } from '@/lib/requestDraft';
import { renderApp, signedIn } from '@/test/render';
import { captureBody, heading } from '@/test/screens';

const KEY = requestDraftKey({ companyId: 7, contactId: 101 });

/**
 * C-9 (аудит 2026-10-18): черновик «Нового запроса» жил только в useState и пропадал при уходе со страницы.
 * Теперь — sessionStorage (ключ с компанией и контактом), очистка после отправки и по «Отмена»;
 * без доступа к хранилищу страница работает как раньше.
 */
describe('«Новый запрос»: черновик переживает уход со страницы', () => {
  it('ключ привязан к компании и контакту', () => {
    expect(requestDraftKey({ companyId: 7, contactId: 101 })).toBe('cabinet.requestDraft.v1.7.101');
    expect(requestDraftKey({ companyId: 7, contactId: 102 })).not.toBe(requestDraftKey({ companyId: 7, contactId: 101 }));
    expect(requestDraftKey({ companyId: 8, contactId: 101 })).not.toBe(requestDraftKey({ companyId: 7, contactId: 101 }));
  });

  it('суть и строки возвращаются после ухода на другую страницу и обратно', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/requests/new');
    await heading('Новая заявка');
    await user.type(screen.getByLabelText('Что нужно'), 'Кабель для цеха');
    await user.type(screen.getByLabelText('Строка 1'), 'Кабель ВВГнг 3×2,5');
    await user.type(screen.getByLabelText('Количество'), '2,5');
    await user.type(screen.getByLabelText('Единица'), 'км');

    await router.navigate('/requests');
    await heading('Заявки');
    await router.navigate('/requests/new');
    await heading('Новая заявка');
    // Х-18: черновик предлагается, а не подставляется молча
    expect(screen.getByLabelText('Что нужно')).toHaveValue('');
    expect(screen.getByText(/^У вас есть черновик от /)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Продолжить' }));
    expect(screen.getByLabelText('Что нужно')).toHaveValue('Кабель для цеха');
    expect(screen.getByLabelText('Строка 1')).toHaveValue('Кабель ВВГнг 3×2,5');
    expect(screen.getByLabelText('Количество')).toHaveValue('2,5');
    expect(screen.getByLabelText('Единица')).toHaveValue('км');
  });

  it('после отправки черновик стирается — новая форма пустая', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/requests/new');
    await heading('Новая заявка');
    await user.type(screen.getByLabelText('Что нужно'), 'Нужно что-то');
    expect(loadRequestDraft(KEY)).not.toBeNull();
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    await heading(/^Заявка ЗВ-/);
    expect(loadRequestDraft(KEY)).toBeNull();
    expect(window.sessionStorage.getItem(KEY)).toBeNull();

    await router.navigate('/requests/new');
    await heading('Новая заявка');
    expect(screen.getByLabelText('Что нужно')).toHaveValue('');
  });

  it('«Отмена» — осознанный отказ: черновик стирается', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.type(screen.getByLabelText('Что нужно'), 'Передумал');
    await user.click(screen.getByRole('link', { name: 'Отмена' }));
    await heading('Заявки');
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
  });

  it('предзаполнение из каталога главнее старого черновика', async () => {
    signedIn();
    window.sessionStorage.setItem(KEY, JSON.stringify({ summary: 'Старый черновик', lines: [{ text: 'Болт', quantity: '', unit: '' }] }));
    const user = userEvent.setup();
    renderApp('/catalog/1001');
    await heading('Подшипник 6205-2RS');
    await user.click(screen.getByRole('button', { name: 'Запросить' }));
    await heading('Новая заявка');
    expect(screen.getByLabelText('Что нужно')).toHaveValue('Нужна позиция из каталога: Подшипник 6205-2RS');
  });

  it('Х-18: сохранённый черновик не подставляется молча — предложение с датой, до выбора он цел', async () => {
    window.sessionStorage.setItem(KEY, JSON.stringify({ summary: 'Кабель', lines: [], attachments: [], savedAt: Date.now() }));
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новая заявка');
    expect(screen.getByText(/^У вас есть черновик от /)).toBeInTheDocument();
    expect(screen.getByLabelText('Что нужно')).toHaveValue('');
    // форма может быть дополнена, но пока выбор не сделан, черновик в хранилище не затирается
    await user.type(screen.getByLabelText('Что нужно'), 'Другое');
    expect(loadRequestDraft(KEY)?.summary).toBe('Кабель');
  });

  it('Х-18: «Начать заново» стирает черновик и убирает предложение', async () => {
    window.sessionStorage.setItem(KEY, JSON.stringify({ summary: 'Кабель', lines: [], attachments: [], savedAt: Date.now() }));
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.click(screen.getByRole('button', { name: 'Начать заново' }));
    expect(screen.queryByText(/^У вас есть черновик от /)).toBeNull();
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
    expect(screen.getByLabelText('Что нужно')).toHaveValue('');
  });

  it('Х-18: «Продолжить» поднимает черновик, предложение исчезает, правки снова сохраняются', async () => {
    window.sessionStorage.setItem(KEY, JSON.stringify({ summary: 'Кабель', lines: [], attachments: [], savedAt: Date.now() }));
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.click(screen.getByRole('button', { name: 'Продолжить' }));
    expect(screen.queryByText(/^У вас есть черновик от /)).toBeNull();
    await user.type(screen.getByLabelText('Что нужно'), ' 5 км');
    expect(loadRequestDraft(KEY)?.summary).toBe('Кабель 5 км');
  });

  it('битый черновик в хранилище игнорируется', async () => {
    signedIn();
    window.sessionStorage.setItem(KEY, '{не json');
    renderApp('/requests/new');
    await heading('Новая заявка');
    expect(screen.getByLabelText('Что нужно')).toHaveValue('');
  });

  it.each([1e20, Date.now() + 10 * 24 * 60 * 60 * 1000])(
    'черновик с датой вне диапазона (%s) отбрасывается, страница не падает',
    async (savedAt) => {
      signedIn();
      window.sessionStorage.setItem(KEY, JSON.stringify({ summary: 'старое', lines: [], attachments: [], savedAt }));
      renderApp('/requests/new');
      await heading('Новая заявка');
      expect(screen.getByLabelText('Что нужно')).toHaveValue('');
      expect(screen.queryByText(/У вас есть черновик/)).not.toBeInTheDocument();
    },
  );

  it('хранилище недоступно (приватный режим, запрет) — форма работает, запрос уходит', async () => {
    signedIn();
    vi.spyOn(window.sessionStorage, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(window.sessionStorage, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(window.sessionStorage, 'removeItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.type(screen.getByLabelText('Что нужно'), 'Без хранилища');
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    expect(await heading(/^Заявка ЗВ-/)).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  // СЦ-10: файлы, приложенные к новой заявке, живут в черновике вместе с текстом.
  const FILE_FIELD = 'Прикрепить файлы (спецификация, опросные листы, чертежи)';

  it('приложенный файл возвращается после ухода и возврата и уходит с заявкой', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/requests');
    const { router } = renderApp('/requests/new');
    await heading('Новая заявка');
    await user.type(screen.getByLabelText('Что нужно'), 'Подшипники по спецификации');
    await user.upload(screen.getByLabelText(FILE_FIELD), new File([new Uint8Array(2048)], 'spec.pdf', { type: 'application/pdf' }));
    expect(await screen.findByText('spec.pdf')).toBeInTheDocument();

    await router.navigate('/requests');
    await heading('Заявки');
    await router.navigate('/requests/new');
    await heading('Новая заявка');
    expect(screen.queryByText('spec.pdf')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Продолжить' }));
    expect(screen.getByText('spec.pdf')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    await heading(/^Заявка ЗВ-/);
    expect(body.current).toMatchObject({ attachments: [{ upload_id: expect.stringMatching(/^upl_/), name: 'spec.pdf' }] });
  });

  it('черновик только с файлом не считается пустым', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.upload(screen.getByLabelText(FILE_FIELD), new File([new Uint8Array(16)], 'drawing.pdf', { type: 'application/pdf' }));
    expect(await screen.findByText('drawing.pdf')).toBeInTheDocument();
    expect(loadRequestDraft(KEY)?.attachments).toHaveLength(1);
  });

  it('черновик старше суток отбрасывается', async () => {
    window.sessionStorage.setItem(
      KEY,
      JSON.stringify({ summary: 'Старое', lines: [], attachments: [], savedAt: Date.now() - 25 * 3600 * 1000 }),
    );
    signedIn();
    renderApp('/requests/new');
    await heading('Новая заявка');
    expect(screen.getByLabelText('Что нужно')).toHaveValue('');
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
  });

  it('прежний формат без файлов и времени читается', async () => {
    window.sessionStorage.setItem(KEY, JSON.stringify({ summary: 'Кабель', lines: [{ text: 'Болт', quantity: '', unit: '' }] }));
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.click(screen.getByRole('button', { name: 'Продолжить' }));
    expect(screen.getByLabelText('Что нужно')).toHaveValue('Кабель');
  });

  it('файл, которого уже нет на сервере: сообщение, файл убран, текст остаётся', async () => {
    window.sessionStorage.setItem(
      KEY,
      JSON.stringify({ summary: 'Кабель', lines: [], attachments: [{ upload_id: 'upl_gone', name: 'old.pdf' }], savedAt: Date.now() }),
    );
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.click(screen.getByRole('button', { name: 'Продолжить' }));
    expect(screen.getByText('old.pdf')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    expect(await screen.findByText('Загруженный файл не найден — загрузите его ещё раз.')).toBeInTheDocument();
    expect(screen.queryByText('old.pdf')).toBeNull();
    expect(loadRequestDraft(KEY)?.attachments).toEqual([]);
    expect(loadRequestDraft(KEY)?.summary).toBe('Кабель');
  });
});
