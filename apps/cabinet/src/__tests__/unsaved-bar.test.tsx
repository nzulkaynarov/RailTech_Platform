import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, heading } from '@/test/screens';

/** Бар несохранённых изменений «Компании» (CAB-FIX-3, K9): место зарезервировано, одна кнопка, вопрос при уходе. */
describe('бар несохранённых изменений «Компании»', () => {
  async function openForm() {
    signedIn();
    const user = userEvent.setup();
    const view = renderApp('/company');
    await user.click(await screen.findByRole('button', { name: 'Изменить' }));
    return { user, ...view };
  }

  /** Место бара — последний элемент формы, есть и без правок (форма не прыгает на первом символе). */
  function dock() {
    const form = screen.getByLabelText('Название').closest('form') as HTMLFormElement;
    const last = form.lastElementChild as HTMLElement;
    expect(last).toHaveAttribute('data-save-dock');
    return { form, dock: last, bar: last.querySelector('[role="region"]') as HTMLElement };
  }

  it('без правок бар невидим, но стоит в форме; после ввода — тот же элемент виден, кнопка «Сохранить» одна', async () => {
    const { user } = await openForm();
    const before = dock();
    expect(before.bar).toHaveAttribute('aria-hidden', 'true');
    expect(before.bar).toHaveAttribute('inert');
    expect(before.bar).toHaveClass('invisible');
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('ИНН'), '7');
    const after = dock();
    expect(after.dock).toBe(before.dock);
    expect(after.bar).not.toHaveAttribute('aria-hidden');
    expect(after.bar).not.toHaveClass('invisible');
    expect(screen.getAllByRole('button', { name: 'Сохранить' })).toHaveLength(1);
    expect(within(after.bar).getByRole('button', { name: 'Сохранить' })).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('Ctrl+S сохраняет только изменённое; без правок сочетание остаётся браузеру', async () => {
    const { user } = await openForm();
    const idle = fireEvent.keyDown(window, { key: 's', code: 'KeyS', ctrlKey: true });
    expect(idle).toBe(true); // не отменено — браузер сам решает

    const body = captureBody('/company');
    await user.type(screen.getByLabelText('ИНН'), '7');
    // раскладка RU: key «ы», клавиша та же
    const handled = fireEvent.keyDown(window, { key: 'ы', code: 'KeyS', ctrlKey: true });
    expect(handled).toBe(false);
    expect(await screen.findByText('Профиль компании сохранён')).toBeInTheDocument();
    expect(body.current).toEqual({ inn: '3051234567' });
  });

  it('«Сбросить» спрашивает; «Продолжить правку» оставляет введённое, подтверждение возвращает сохранённое', async () => {
    const { user } = await openForm();
    const inn = screen.getByLabelText('ИНН');
    await user.type(inn, '7');
    await user.click(screen.getByRole('button', { name: 'Сбросить' }));
    const dialog = await screen.findByRole('dialog', { name: 'Сбросить изменения?' });
    await user.click(within(dialog).getByRole('button', { name: 'Продолжить правку' }));
    expect(inn).toHaveValue('3051234567');

    await user.click(screen.getByRole('button', { name: 'Сбросить' }));
    await user.click(within(await screen.findByRole('dialog', { name: 'Сбросить изменения?' })).getByRole('button', { name: 'Сбросить' }));
    expect(inn).toHaveValue('305123456');
    expect(dock().bar).toHaveAttribute('aria-hidden', 'true');
  });

  it('уход по ссылке меню с правками спрашивает «Выйти без сохранения?»; «Остаться» — правки на месте', async () => {
    const { user, router } = await openForm();
    await user.type(screen.getByLabelText('ИНН'), '7');
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    await user.click(within(side).getByRole('link', { name: 'Запросы' }));
    const dialog = await screen.findByRole('dialog', { name: 'Выйти без сохранения?' });
    await user.click(within(dialog).getByRole('button', { name: 'Остаться' }));
    expect(router.state.location.pathname).toBe('/company');
    expect(screen.getByLabelText('ИНН')).toHaveValue('3051234567');

    await user.click(within(side).getByRole('link', { name: 'Запросы' }));
    await user.click(within(await screen.findByRole('dialog', { name: 'Выйти без сохранения?' })).getByRole('button', { name: 'Выйти без сохранения' }));
    await heading('Запросы');
  });

  it('без правок уход — без вопроса; закрытие вкладки с правками — предупреждение браузера', async () => {
    const { user } = await openForm();
    const unload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(false);

    await user.type(screen.getByLabelText('ИНН'), '7');
    const dirtyUnload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(dirtyUnload);
    expect(dirtyUnload.defaultPrevented).toBe(true);

    await user.click(screen.getByRole('button', { name: 'Сбросить' }));
    await user.click(within(await screen.findByRole('dialog', { name: 'Сбросить изменения?' })).getByRole('button', { name: 'Сбросить' }));
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    await user.click(within(side).getByRole('link', { name: 'Запросы' }));
    await heading('Запросы');
  });

  it('«Закрыть» с правками спрашивает; без правок — сразу к просмотру', async () => {
    const { user } = await openForm();
    await user.type(screen.getByLabelText('ИНН'), '7');
    await user.click(screen.getByRole('button', { name: 'Закрыть' }));
    await user.click(within(await screen.findByRole('dialog', { name: 'Выйти без сохранения?' })).getByRole('button', { name: 'Выйти без сохранения' }));
    expect(await screen.findByText('305123456')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Изменить' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Изменить' }));
    await user.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Изменить' })).toBeInTheDocument();
  });
});
