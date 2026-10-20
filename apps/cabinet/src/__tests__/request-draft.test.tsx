import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { loadRequestDraft, requestDraftKey } from '@/lib/requestDraft';
import { renderApp, signedIn } from '@/test/render';
import { heading } from '@/test/screens';

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
    await heading('Новый запрос');
    await user.type(screen.getByLabelText('Что нужно'), 'Кабель для цеха');
    await user.type(screen.getByLabelText('Строка 1'), 'Кабель ВВГнг 3×2,5');
    await user.type(screen.getByLabelText('Количество'), '2,5');
    await user.type(screen.getByLabelText('Единица'), 'км');

    await router.navigate('/requests');
    await heading('Запросы');
    await router.navigate('/requests/new');
    await heading('Новый запрос');

    expect(screen.getByLabelText('Что нужно')).toHaveValue('Кабель для цеха');
    expect(screen.getByLabelText('Строка 1')).toHaveValue('Кабель ВВГнг 3×2,5');
    expect(screen.getByLabelText('Количество')).toHaveValue('2,5');
    expect(screen.getByLabelText('Единица')).toHaveValue('км');
  });

  it('после отправки черновик стирается — новая форма пустая', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/requests/new');
    await heading('Новый запрос');
    await user.type(screen.getByLabelText('Что нужно'), 'Нужно что-то');
    expect(loadRequestDraft(KEY)).not.toBeNull();
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    await heading(/^Запрос Z-/);
    expect(loadRequestDraft(KEY)).toBeNull();
    expect(window.sessionStorage.getItem(KEY)).toBeNull();

    await router.navigate('/requests/new');
    await heading('Новый запрос');
    expect(screen.getByLabelText('Что нужно')).toHaveValue('');
  });

  it('«Отмена» — осознанный отказ: черновик стирается', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новый запрос');
    await user.type(screen.getByLabelText('Что нужно'), 'Передумал');
    await user.click(screen.getByRole('link', { name: 'Отмена' }));
    await heading('Запросы');
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
  });

  it('предзаполнение из каталога главнее старого черновика', async () => {
    signedIn();
    window.sessionStorage.setItem(KEY, JSON.stringify({ summary: 'Старый черновик', lines: [{ text: 'Болт', quantity: '', unit: '' }] }));
    const user = userEvent.setup();
    renderApp('/catalog/1001');
    await heading('Подшипник 6205-2RS');
    await user.click(screen.getByRole('button', { name: 'Запросить' }));
    await heading('Новый запрос');
    expect(screen.getByLabelText('Что нужно')).toHaveValue('Нужна позиция из каталога: Подшипник 6205-2RS');
  });

  it('битый черновик в хранилище игнорируется', async () => {
    signedIn();
    window.sessionStorage.setItem(KEY, '{не json');
    renderApp('/requests/new');
    await heading('Новый запрос');
    expect(screen.getByLabelText('Что нужно')).toHaveValue('');
  });

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
    await heading('Новый запрос');
    await user.type(screen.getByLabelText('Что нужно'), 'Без хранилища');
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(await heading(/^Запрос Z-/)).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});
