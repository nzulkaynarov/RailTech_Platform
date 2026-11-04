import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading, requestLog } from '@/test/screens';

/** Мастер загрузки прайса (PART-2): файл и срок → проверка с ошибками по строкам → «Загрузить» → отчёт. */

const PARTNER = { roles: ['partner' as const], modules: ['my_products', 'catalog_requests', 'profile'] };
const xlsx = (name: string) => new File([new Uint8Array([0x50, 0x4b, 3, 4])], name, { type: 'application/octet-stream' });

async function openWizard() {
  signedIn('actor', 'demo', PARTNER);
  // accept=".xlsx" поля файла в тесте не режет выбор: проверку типа делает сам мастер
  const user = userEvent.setup({ applyAccept: false });
  const view = renderApp('/my-products');
  await heading('Мои товары');
  await user.click(await screen.findByRole('button', { name: 'Загрузить прайс' }));
  const dialog = await screen.findByRole('dialog', { name: 'Загрузка прайса' });
  return { user, dialog, ...view };
}

async function chooseAndCheck(user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement, name: string) {
  await user.upload(within(dialog).getByLabelText('2. Выберите заполненный файл'), xlsx(name));
  await user.click(within(dialog).getByRole('button', { name: 'Проверить файл' }));
}

describe('Мастер загрузки прайса', () => {
  it('шаблон, файл, проверка без записи, «Загрузить» и отчёт; новые карточки — в черновиках', async () => {
    const { user, dialog } = await openWizard();
    const log = requestLog();
    expect(within(dialog).getByRole('button', { name: 'Проверить файл' })).toBeDisabled(); // файла нет
    await user.click(within(dialog).getByRole('button', { name: 'Скачать шаблон' }));
    await waitFor(() => expect(log).toContain('GET /partner/price-template'));

    await chooseAndCheck(user, dialog, 'prices.xlsx');
    expect(await within(dialog).findByText('Проверяем файл…')).toBeInTheDocument();
    expect(await within(dialog).findByText('Проверка завершена')).toBeInTheDocument();
    expect(within(dialog).getByText('Ошибок нет — можно загружать.')).toBeInTheDocument();
    expect(log.filter((entry) => entry === 'POST /partner/price-list')).toHaveLength(1);
    // предпросмотр ничего не записал: в списке по-прежнему 8 карточек
    expect(screen.getByRole('button', { name: 'Все 8', hidden: true })).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Загрузить' }));
    expect(await within(dialog).findByText('Прайс загружен')).toBeInTheDocument();
    expect(log.filter((entry) => entry === 'POST /partner/price-list')).toHaveLength(2);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Все 11', hidden: true })).toBeInTheDocument());
    await user.click(within(dialog).getByRole('button', { name: 'Перейти к черновикам' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Черновики 6' })).toHaveAttribute('aria-pressed', 'true'));
  });

  it('ошибки по строкам: номер строки, поле и что исправить; без ошибочных строк загрузить можно', async () => {
    const { user, dialog } = await openWizard();
    await chooseAndCheck(user, dialog, 'errors.xlsx');
    expect(await within(dialog).findByText('Проверка завершена')).toBeInTheDocument();
    expect(within(dialog).getByText(/В 3 строках ошибки/)).toBeInTheDocument();
    const table = within(dialog).getByRole('list', { name: 'Что исправить' });
    const rows = within(table).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Строка 4 · Цена');
    expect(within(rows[0]).getByText('Цена должна быть числом, например 150.50.')).toBeInTheDocument();
    expect(rows[1]).toHaveTextContent('Строка 7 · Категория');
    expect(within(rows[1]).getByText(/Категории «Крепёж» нет в справочнике/)).toBeInTheDocument();
    expect(rows[2]).toHaveTextContent('Строка 12 · Валюта');
    expect(within(rows[2]).getByText(/Валюты «US» нет в справочнике/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Кода ТН ВЭД «8708309999» нет в классификаторе/)).toBeInTheDocument();
    expect(within(dialog).getByText(/карточку нельзя будет опубликовать без дополнений/)).toBeInTheDocument();
    await expectNoAxeViolations();
    await user.click(within(dialog).getByRole('button', { name: 'Загрузить без ошибочных строк' }));
    expect(await within(dialog).findByText('Прайс загружен')).toBeInTheDocument();
  });

  it('уже известные товары: предложения изменений, цены записаны', async () => {
    const { user, dialog } = await openWizard();
    await chooseAndCheck(user, dialog, 'existing.xlsx');
    expect(await within(dialog).findByText('Изменения полей карточек')).toBeInTheDocument();
    expect(within(dialog).getByText(/Ваши цены записаны, а правки полей мы отправили на проверку/)).toBeInTheDocument();
    expect(within(dialog).getByText('Наименование, Категория')).toBeInTheDocument();
  });

  it('файл без колонки «Наименование» не принят: понятная причина и «Попробовать снова»', async () => {
    const { user, dialog } = await openWizard();
    await chooseAndCheck(user, dialog, 'broken.xlsx');
    expect(await within(dialog).findByText('Файл не принят')).toBeInTheDocument();
    expect(within(dialog).getByText(/В файле нет колонки «Наименование»/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Попробовать снова' }));
    expect(await within(dialog).findByRole('button', { name: 'Проверить файл' })).toBeInTheDocument();
  });

  it('не Excel и слишком большой файл отклоняются до отправки', async () => {
    const { user, dialog } = await openWizard();
    const log = requestLog();
    await user.upload(within(dialog).getByLabelText('2. Выберите заполненный файл'), new File(['x'], 'price.csv', { type: 'text/csv' }), );
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Нужен файл Excel (.xlsx).');
    expect(within(dialog).getByRole('button', { name: 'Проверить файл' })).toBeDisabled();
    const big = new File([new Uint8Array(1)], 'big.xlsx');
    Object.defineProperty(big, 'size', { value: 21 * 1024 * 1024 });
    await user.upload(within(dialog).getByLabelText(/Заменить файл|Выберите заполненный файл/), big).catch(() => undefined);
    expect(log.filter((entry) => entry.startsWith('POST'))).toHaveLength(0);
  });

  it('срок цен: неполная дата и «до» раньше «с» не дают проверить файл', async () => {
    const { user, dialog } = await openWizard();
    await user.upload(within(dialog).getByLabelText('2. Выберите заполненный файл'), xlsx('prices.xlsx'));
    const from = within(dialog).getByLabelText('Цены действуют с');
    const until = within(dialog).getByLabelText('Цены действуют до');
    await user.type(from, '0112');
    expect(within(dialog).getByText('Введите дату полностью: ДД.ММ.ГГГГ.')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Проверить файл' })).toBeDisabled();
    await user.clear(from);
    await user.type(from, '01122026');
    await user.type(until, '01112026');
    expect(within(dialog).getByText('Срок «до» не может быть раньше срока «с».')).toBeInTheDocument();
    await user.clear(until);
    await user.type(until, '31122027');
    expect(within(dialog).getByRole('button', { name: 'Проверить файл' })).toBeEnabled();
  });
});
