import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, failWith, heading, requestLog } from '@/test/screens';

describe('Заявки', () => {
  it('список: номер, суть, статус, сделка; строка открывается с клавиатуры', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/requests');
    await heading('Заявки');
    const list = await screen.findByRole('list', { name: 'Заявки' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(6);
    expect(within(list).getByText('Новая')).toBeInTheDocument();
    expect(within(list).getAllByText('Есть предложение')).toHaveLength(2);
    expect(within(list).getByText('Ещё без проекта')).toBeInTheDocument();

    const link = within(list).getByRole('link', { name: /^ЗВ-2026-042/ });
    link.focus();
    await user.keyboard('{Enter}');
    expect(await heading('Заявка ЗВ-2026-042')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests/501');
  });

  it('карточка: что дальше и КП по запросу', async () => {
    signedIn();
    renderApp('/requests/501');
    await heading('Заявка ЗВ-2026-042');
    expect(screen.getByText('Предложение готово — откройте его ниже.')).toBeInTheDocument();
    expect(screen.getByText('Через менеджера')).toBeInTheDocument();
    expect(screen.getByText('Ведёт')).toBeInTheDocument();
    expect(screen.getByText('Дилноза Каримова')).toBeInTheDocument();
    const quotes = await screen.findByRole('link', { name: /KP-2026-0042 · версия 2/ });
    expect(quotes).toHaveAttribute('href', '/quotes/301');
    await expectNoAxeViolations();
  });

  it('карточка: пока КП не ушло клиенту — «В работе», а не «Есть предложение» (КАБ-1)', async () => {
    signedIn();
    renderApp('/requests/502');
    await heading('Заявка ПР-2026-057');
    expect(screen.getByText('Готовим коммерческое предложение.')).toBeInTheDocument();
    expect(screen.queryByText('Предложение готово — откройте его ниже.')).not.toBeInTheDocument();
    expect(screen.queryByText('Есть предложение')).not.toBeInTheDocument();
  });

  it('карточка: без назначенного менеджера строки «Ведёт» нет', async () => {
    signedIn();
    renderApp('/requests/503');
    await heading('Заявка ЗВ-2026-061');
    expect(screen.queryByText('Ведёт')).not.toBeInTheDocument();
  });

  it('чужой или несуществующий запрос — «не найдено»', async () => {
    signedIn();
    renderApp('/requests/9999');
    expect(await heading('Страница не найдена')).toBeInTheDocument();
  });

  it('«Новый запрос»: проверка формы, строки свободным текстом → POST /requests по контракту', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/requests');
    const { router } = renderApp('/requests');
    await heading('Заявки');
    await user.click(screen.getByRole('link', { name: 'Новая заявка' }));
    await heading('Новая заявка');

    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    expect(screen.getByText('Опишите, что нужно, — хотя бы одной фразой.')).toBeInTheDocument();
    expect(screen.getByLabelText('Что нужно')).toHaveAttribute('aria-invalid', 'true');

    await user.type(screen.getByLabelText('Что нужно'), 'Кабель для цеха');
    await user.type(screen.getByLabelText('Строка 1'), 'Кабель ВВГнг 3×2,5');
    await user.type(screen.getByLabelText('Количество'), 'много');
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    expect(screen.getByText(/Количество — положительное число/)).toBeInTheDocument();

    await user.clear(screen.getByLabelText('Количество'));
    await user.type(screen.getByLabelText('Количество'), '2,5');
    await user.type(screen.getByLabelText('Единица'), 'км');
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }));
    await user.type(screen.getByLabelText('Строка 2'), 'Монтаж');
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }));
    await user.click(screen.getByRole('button', { name: 'Удалить строку 3' }));
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));

    expect(await heading('Заявка ЗВ-2026-107')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests/507');
    expect(body.current).toEqual({
      summary: 'Кабель для цеха',
      lines: [
        { text: 'Кабель ВВГнг 3×2,5', quantity: '2.5', unit: 'км' },
        { text: 'Монтаж', quantity: null, unit: null },
      ],
    });
    expect(await screen.findByText('Заявка ЗВ-2026-107 отправлена')).toBeInTheDocument();
  });

  it('Ctrl+S / ⌘S не отправляет запрос и не перехватывается: отправка — только кнопкой рядом с «Что произойдёт»', async () => {
    signedIn();
    const user = userEvent.setup();
    const log = requestLog();
    const body = captureBody('/requests');
    const { router } = renderApp('/requests/new');
    await heading('Новая заявка');
    await user.type(screen.getByLabelText('Что нужно'), 'Кабель для цеха');

    for (const modifier of ['ctrlKey', 'metaKey'] as const) {
      const event = new KeyboardEvent('keydown', { key: 's', [modifier]: true, bubbles: true, cancelable: true });
      window.dispatchEvent(event);
      // Сочетание остаётся браузеру: кабинет его не гасит.
      expect(event.defaultPrevented).toBe(false);
    }
    expect(screen.queryByRole('region', { name: /несохранённые изменения/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Сохранить/ })).not.toBeInTheDocument();
    expect(log).not.toContain('POST /requests');
    expect(router.state.location.pathname).toBe('/requests/new');

    // «Что произойдёт» — только настоящий процесс: номер, менеджер, КП в разделе «КП», без сроков.
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Что произойдёт');
    expect(note).toHaveTextContent('Заявка получит номер и уйдёт менеджеру');
    expect(note).not.toHaveTextContent(/\d|час|рабоч/i);
    // Выбора «Направление обращения» нет: в контракте такого поля нет.
    expect(screen.queryByText(/Направление обращения/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    await heading(/^Заявка ЗВ-/);
    // Тело POST — ровно поля ClientRequestCreate, ничего лишнего.
    expect(body.current).toEqual({ summary: 'Кабель для цеха', lines: [] });
  });

  it('старая ссылка ?view=… ведёт на список запросов, а не в 404', async () => {
    signedIn();
    const { router } = renderApp('/requests?view=kanban');
    await heading('Заявки');
    expect(await screen.findByRole('list', { name: 'Заявки' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests');
    expect(router.state.location.search).toBe('');
  });

  it('подсказки по контракту: суть до 5000 символов, файл до 10 МБ', async () => {
    signedIn();
    renderApp('/requests/new');
    await heading('Новая заявка');
    expect(screen.getByText(/До 5000 символов/)).toBeInTheDocument();
    expect(screen.getByLabelText('Что нужно')).toHaveAttribute('maxlength', '5000');
    expect(screen.getByText('PDF, DOCX, XLSX или изображения до 10 МБ')).toBeInTheDocument();
    expect(screen.queryByText(/20 МБ/)).not.toBeInTheDocument();
  });

  it('вложение: загрузка → в запрос уходят только upload_id и name, без size_bytes; размер виден в форме', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/requests');
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.type(screen.getByLabelText('Что нужно'), 'Нужны подшипники по спецификации');
    await user.upload(
      screen.getByLabelText('Прикрепить файлы (спецификация, опросные листы, чертежи)'),
      new File([new Uint8Array(2048)], 'spec.pdf', { type: 'application/pdf' }),
    );
    expect(await screen.findByText('spec.pdf')).toBeInTheDocument();
    expect(screen.getByText(/^\(2 (КБ|кБ|KB)\)$/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    await heading(/^Заявка ЗВ-/);
    expect(body.current).toEqual({
      summary: 'Нужны подшипники по спецификации',
      lines: [],
      attachments: [{ upload_id: expect.stringMatching(/^upl_/), name: 'spec.pdf' }],
    });
  });

  it('файл больше 10 МБ не загружается: сообщение, запроса /uploads нет', async () => {
    signedIn();
    const user = userEvent.setup();
    const log = requestLog();
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.upload(
      screen.getByLabelText('Прикрепить файлы (спецификация, опросные листы, чертежи)'),
      new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'huge.pdf', { type: 'application/pdf' }),
    );
    expect(await screen.findByText('Файл больше 10 МБ.')).toBeInTheDocument();
    expect(screen.queryByText('huge.pdf')).not.toBeInTheDocument();
    expect(log).not.toContain('POST /uploads');
  });

  it('ошибка ERP при отправке — текст по коду, форма не теряется', async () => {
    signedIn();
    failWith('post', '/requests', 422, 'VALIDATION_ERROR');
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новая заявка');
    await user.type(screen.getByLabelText('Что нужно'), 'Нужно что-то');
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    expect(await screen.findByText('Проверьте заполненные поля.')).toBeInTheDocument();
    expect(screen.getByLabelText('Что нужно')).toHaveValue('Нужно что-то');
  });

  it('can_act=false: «Новый запрос» скрыт, прямой адрес формы объясняет почему', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    const { router } = renderApp('/requests');
    await heading('Заявки');
    await screen.findByRole('list', { name: 'Заявки' });
    expect(screen.queryByRole('link', { name: 'Новая заявка' })).not.toBeInTheDocument();
    await router.navigate('/requests/new');
    expect(await screen.findByText('Создавать заявки может коллега с правом подтверждать')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отправить заявку' })).not.toBeInTheDocument();
    // Two screens in one test: ~12 s alone, over 30 s under the full parallel run (as journey-j6).
  }, 60_000);

  it('пустой список — пустое состояние', async () => {
    signedIn('actor', 'empty');
    renderApp('/requests');
    expect(await screen.findByText('Заявок пока нет')).toBeInTheDocument();
  });

  it('axe: список и форма', async () => {
    signedIn();
    const { router } = renderApp('/requests');
    await screen.findByRole('list', { name: 'Заявки' });
    await expectNoAxeViolations();
    await router.navigate('/requests/new');
    await heading('Новая заявка');
    await expectNoAxeViolations();
    // Two axe passes: ~11 s alone, over 30 s under the full parallel run (as journey-j6).
  }, 60_000);
});
