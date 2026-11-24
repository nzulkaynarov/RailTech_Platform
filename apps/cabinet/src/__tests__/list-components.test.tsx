import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter } from 'react-router-dom';

import { NoMatchState } from '@/components/EmptyState';
import { CompactList } from '@/components/list/CompactList';
import { CutText } from '@/components/list/CutText';
import { ListToolbar } from '@/components/list/ListToolbar';
import { RowMenu, RowMenuAction, RowMenuLink } from '@/components/list/RowMenu';
import '@/i18n';

/** Общие компоненты списков кабинета (RowMenu, CompactList, ListToolbar, NoMatchState, CutText). */
describe('RowMenu', () => {
  it('одна кнопка «Действия: <имя>»; пункты — в меню; ссылка ведёт по адресу, действие вызывает обработчик', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <MemoryRouter>
        <RowMenu name="S-1">
          <RowMenuLink to="/requests/new">Повторить</RowMenuLink>
          <RowMenuAction onSelect={onSelect}>Скачать</RowMenuAction>
        </RowMenu>
      </MemoryRouter>,
    );
    expect(screen.queryByRole('menuitem')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Действия: S-1' }));
    expect(await screen.findByRole('menuitem', { name: 'Повторить' })).toHaveAttribute('href', '/requests/new');
    await user.click(screen.getByRole('menuitem', { name: 'Скачать' }));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});

describe('CompactList', () => {
  const items = Array.from({ length: 6 }, (_, index) => <li key={index}>Строка {index + 1}</li>);

  it('показывает первые limit, «Показать все (N)» раскрывает, «Свернуть» возвращает', async () => {
    const user = userEvent.setup();
    render(<CompactList items={items} limit={4} label="Список" />);
    expect(within(screen.getByRole('list', { name: 'Список' })).getAllByRole('listitem')).toHaveLength(4);
    await user.click(screen.getByRole('button', { name: 'Показать все (6)' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(6);
    await user.click(screen.getByRole('button', { name: 'Свернуть' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(4);
  });

  it('не больше limit — кнопки нет', () => {
    render(<CompactList items={items.slice(0, 4)} limit={4} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(4);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('ListToolbar', () => {
  function Harness({ count, display }: { count: number; display?: 'pills' }) {
    const [value, setValue] = useState('');
    const [query, setQuery] = useState('');
    const options = [{ value: '', label: 'Все' }, ...Array.from({ length: count - 1 }, (_, i) => ({ value: `s${i}`, label: `Статус ${i}` }))];
    return (
      <>
        <ListToolbar
          filterLabel="Статус"
          options={options}
          value={value}
          onChange={setValue}
          display={display}
          search={{ value: query, onChange: setQuery, placeholder: 'Поиск' }}
        />
        <output data-testid="state">{`${value}|${query}`}</output>
      </>
    );
  }

  it('до 4 значений — кнопки с aria-pressed; поиск в той же панели', async () => {
    const user = userEvent.setup();
    render(<Harness count={3} />);
    const toolbar = screen.getByTestId('list-toolbar');
    expect(within(toolbar).getByRole('button', { name: 'Все' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(within(toolbar).getByRole('button', { name: 'Статус 1' }));
    expect(within(toolbar).getByRole('button', { name: 'Статус 1' })).toHaveAttribute('aria-pressed', 'true');
    await user.type(within(toolbar).getByRole('searchbox', { name: 'Поиск' }), 'ab');
    expect(screen.getByTestId('state')).toHaveTextContent('s1|ab');
  });

  it('больше 4 значений — выпадающий список вместо кнопок; «все» возвращает пустое значение', async () => {
    const user = userEvent.setup();
    render(<Harness count={6} />);
    const toolbar = screen.getByTestId('list-toolbar');
    expect(within(toolbar).queryByRole('button', { name: 'Статус 2' })).not.toBeInTheDocument();
    await user.click(within(toolbar).getByRole('combobox', { name: 'Статус' }));
    await user.click(await screen.findByRole('option', { name: 'Статус 2' }));
    expect(screen.getByTestId('state')).toHaveTextContent('s2|');
    await user.click(within(toolbar).getByRole('combobox', { name: 'Статус' }));
    await user.click(await screen.findByRole('option', { name: 'Все' }));
    expect(screen.getByTestId('state')).toHaveTextContent('|');
  });

  it('display="pills" — кнопки и при шести значениях', () => {
    render(<Harness count={6} display="pills" />);
    expect(screen.getByRole('button', { name: 'Статус 4' })).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
});

describe('NoMatchState и CutText', () => {
  it('«ничего не найдено» с кнопкой сброса', async () => {
    const user = userEvent.setup();
    const onReset = vi.fn();
    render(<NoMatchState title="Не найдено" text="Измените запрос" resetLabel="Сбросить" onReset={onReset} />);
    expect(screen.getByRole('heading', { name: 'Не найдено' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Сбросить' }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it('обрезанный текст: полный текст в подсказке и в дереве', () => {
    render(<CutText text="Очень длинное описание позиции заявки" lines={2} />);
    const node = screen.getByText('Очень длинное описание позиции заявки');
    expect(node).toHaveAttribute('title', 'Очень длинное описание позиции заявки');
    expect(node.className).toContain('line-clamp-2');
  });
});
