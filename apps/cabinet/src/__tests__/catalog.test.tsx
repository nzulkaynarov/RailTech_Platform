import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

function results() {
  return screen.findByRole('list', { name: 'Позиции каталога' });
}

describe('Каталог', () => {
  it('опубликованный слой: цена-витрина или «по запросу», наличие статусом, срок', async () => {
    signedIn();
    renderApp('/catalog');
    await heading('Каталог');
    const list = await results();
    expect(screen.getByText('Найдено 24 позиции')).toBeInTheDocument();
    expect(within(list).getAllByRole('listitem')).toHaveLength(12);
    const bearing = within(list).getByRole('link', { name: 'Подшипник 6205-2RS' }).closest('article') as HTMLElement;
    expect(within(bearing).getByText('165 000 UZS')).toBeInTheDocument();
    expect(within(bearing).getByText('В наличии')).toBeInTheDocument();
    expect(within(bearing).getByText('срок 2 дня')).toBeInTheDocument();
    const service = within(list).getByRole('link', { name: 'Пусконаладка насосного оборудования' }).closest('article') as HTMLElement;
    expect(within(service).getByText('Цена по запросу')).toBeInTheDocument();
    expect(within(service).getByText('Услуга')).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('пагинация, поиск и категории — в адресе страницы', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/catalog');
    await results();
    expect(screen.getByText('Страница 1 из 2')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Вперёд' }));
    expect(await screen.findByText('Страница 2 из 2')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Задвижка 30с41нж Ду100' })).toBeInTheDocument();
    expect(router.state.location.search).toBe('?page=2');

    await user.type(screen.getByRole('searchbox', { name: 'Поиск по каталогу' }), 'ремень');
    await user.click(screen.getByRole('button', { name: 'Найти' }));
    expect(await screen.findByText('Найдено 3 позиции')).toBeInTheDocument();
    expect(router.state.location.search).toBe('?q=%D1%80%D0%B5%D0%BC%D0%B5%D0%BD%D1%8C');

    await user.click(screen.getByRole('button', { name: 'Очистить поиск' }));
    await user.click(await screen.findByRole('button', { name: 'Услуги' }));
    expect(await screen.findByText('Найдено 2 позиции')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Услуги' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('ничего не нашлось — сброс и «описать в запросе»', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/catalog?q=луноход');
    expect(await screen.findByText('Ничего не нашлось')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Описать в запросе' })).toHaveAttribute('href', '/requests/new');
    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));
    expect(await screen.findByText('Найдено 24 позиции')).toBeInTheDocument();
  });

  it('карточка: характеристики, цена; «Запросить» открывает новый запрос с позицией', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/catalog/1001');
    await heading('Подшипник 6205-2RS');
    expect(screen.getByText('Внутренний диаметр')).toBeInTheDocument();
    expect(screen.getByText('25 мм')).toBeInTheDocument();
    expect(screen.getByText('165 000 UZS')).toBeInTheDocument();
    await expectNoAxeViolations();
    await user.click(screen.getByRole('button', { name: 'Запросить' }));
    await heading('Новый запрос');
    expect(router.state.location.pathname).toBe('/requests/new');
    expect(screen.getByLabelText('Строка 1')).toHaveValue('Подшипник 6205-2RS');
    expect(screen.getByLabelText('Единица')).toHaveValue('шт');
    expect(screen.getByLabelText('Что нужно')).toHaveValue('Нужна позиция из каталога: Подшипник 6205-2RS');
  });

  it('цена по запросу — подсказка; can_act=false — без «Запросить»', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/catalog/1003');
    await heading('Пусконаладка насосного оборудования');
    expect(screen.getByText('Цена по запросу')).toBeInTheDocument();
    expect(screen.getByText(/менеджер пришлёт КП с ценой/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Запросить' })).not.toBeInTheDocument();
  });

  it('чужая/неопубликованная позиция — «не найдено»; пустой каталог', async () => {
    signedIn();
    const { router } = renderApp('/catalog/77');
    expect(await heading('Страница не найдена')).toBeInTheDocument();
    signedIn('actor', 'empty');
    router.navigate('/catalog');
    expect(await screen.findByText('Каталог пуст')).toBeInTheDocument();
  });
});
