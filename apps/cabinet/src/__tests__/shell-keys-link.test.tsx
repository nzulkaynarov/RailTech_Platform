import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { isSidebarToggle, isTypingTarget, shortcutLabel } from '@/lib/keyboard';
import { copyText, shareableUrl } from '@/lib/shareLink';
import { asMiniApp, renderApp, signedIn } from '@/test/render';
import { heading } from '@/test/screens';

const keydown = (init: KeyboardEventInit, target?: EventTarget) => {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
  if (target) Object.defineProperty(event, 'target', { value: target });
  return event;
};

describe('⌘\\ / Ctrl+\\ — сайдбар (CAB-FIX-3, K12)', () => {
  it('по физической клавише: работает и в RU-раскладке, не в полях ввода, не с Shift/Alt', () => {
    expect(isSidebarToggle(keydown({ code: 'Backslash', key: '\\', metaKey: true }))).toBe(true);
    expect(isSidebarToggle(keydown({ code: 'Backslash', key: 'ё', ctrlKey: true }))).toBe(true); // RU
    expect(isSidebarToggle(keydown({ code: 'Backslash', key: '\\' }))).toBe(false);
    expect(isSidebarToggle(keydown({ code: 'Backslash', key: '|', ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(isSidebarToggle(keydown({ code: 'KeyA', key: '\\', ctrlKey: true }))).toBe(false);

    const input = document.createElement('input');
    const textarea = document.createElement('textarea');
    const editable = document.createElement('div');
    editable.setAttribute('contenteditable', 'true');
    const checkbox = Object.assign(document.createElement('input'), { type: 'checkbox' });
    for (const field of [input, textarea, editable]) {
      expect(isTypingTarget(field)).toBe(true);
      expect(isSidebarToggle(keydown({ code: 'Backslash', ctrlKey: true }, field))).toBe(false);
    }
    expect(isTypingTarget(checkbox)).toBe(false);
    expect(isTypingTarget(document.createElement('button'))).toBe(false);
  });

  it('подсказка сочетания: ⌘ на Mac, Ctrl на Windows', () => {
    const platform = vi.spyOn(navigator, 'platform', 'get');
    platform.mockReturnValue('MacIntel');
    expect(shortcutLabel('S')).toBe('⌘S');
    platform.mockReturnValue('Win32');
    const agent = vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Mozilla/5.0 (Windows NT 10.0; Win64; x64)');
    expect(shortcutLabel('S')).toBe('Ctrl+S');
    platform.mockRestore();
    agent.mockRestore();
  });

  it('в оболочке: Ctrl+\\ сворачивает меню, в поле поиска — нет', async () => {
    signedIn();
    renderApp('/catalog');
    await heading('Каталог');
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(within(side).getByText('Запросы')).toBeInTheDocument();

    const search = screen.getByRole('searchbox');
    fireEvent.keyDown(search, { code: 'Backslash', key: '\\', ctrlKey: true });
    expect(within(side).getByText('Запросы')).toBeInTheDocument();

    fireEvent.keyDown(document.body, { code: 'Backslash', key: 'ё', ctrlKey: true });
    await waitFor(() => expect(within(side).queryByText('Запросы')).not.toBeInTheDocument());
    expect(within(side).getByRole('link', { name: 'Запросы' })).toBeInTheDocument();
    fireEvent.keyDown(document.body, { code: 'Backslash', key: '\\', metaKey: true });
    await waitFor(() => expect(within(side).getByText('Запросы')).toBeInTheDocument());
  });
});

describe('«Копировать ссылку» (CAB-FIX-3, K15)', () => {
  it('адрес — origin + pathname и обычные параметры; без #…, tgWebApp*, токенов и utm', () => {
    expect(shareableUrl({ origin: 'https://cabinet.railtech.uz', pathname: '/deals/48', search: '' })).toBe('https://cabinet.railtech.uz/deals/48');
    expect(
      shareableUrl({
        origin: 'https://cabinet.railtech.uz',
        pathname: '/documents',
        search: '?kind=invoice&tgWebAppData=user%3D1&tgWebAppVersion=8.0&token=abc&utm_source=bot&startapp=deal_1',
      }),
    ).toBe('https://cabinet.railtech.uz/documents?kind=invoice');
  });

  it('буфер недоступен или запретил запись — false, без исключения', async () => {
    const original = navigator.clipboard;
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: () => Promise.reject(new Error('denied')) } });
    expect(await copyText('x')).toBe(false);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    expect(await copyText('x')).toBe(false);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: original });
  });

  it('наблюдатель: копируется чистый адрес; ошибка буфера — сообщение словами', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    // userEvent.setup() ставит свой буфер — подменяем после него
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    const original = navigator.clipboard;
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    renderApp('/requests');
    await heading('Запросы');
    await user.click(screen.getByRole('button', { name: 'Копировать ссылку' }));
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}${window.location.pathname}`);
    expect(writeText.mock.calls[0][0]).not.toContain('#');
    expect(await screen.findByText('Ссылка скопирована')).toBeInTheDocument();

    writeText.mockRejectedValueOnce(new Error('denied'));
    await user.click(screen.getByRole('button', { name: 'Копировать ссылку' }));
    expect(await screen.findByText(/Не удалось скопировать ссылку/)).toBeInTheDocument();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: original });
  });

  it('в Mini App кнопки нет — ссылка Telegram не для браузера', async () => {
    asMiniApp({ initData: 'query_id=AAE&user=viewer&hash=signed' });
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/');
    await heading('Запросы');
    expect(screen.getByText('Только просмотр: действия доступны контакту с правом подтверждать')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Копировать ссылку' })).not.toBeInTheDocument();
  });
});
