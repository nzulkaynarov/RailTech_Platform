import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import i18n from '@/i18n';
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
    expect(within(bearing).getByText('165 000 сум')).toBeInTheDocument();
    expect(within(bearing).getByText('В наличии')).toBeInTheDocument();
    expect(within(bearing).getByText('срок 2 дня')).toBeInTheDocument();
    const service = within(list).getByRole('link', { name: 'Пусконаладка насосного оборудования' }).closest('article') as HTMLElement;
    expect(within(service).getByText('Цена по запросу')).toBeInTheDocument();
    expect(within(service).getByText('Услуга')).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  // D-5 (FIX-51): «В наличии» и «срок 0 дней» рядом читается странно — при нулевом сроке срок не показывается.
  it('срок 0 дней не показывается: «В наличии» без срока; положительный срок — как был', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/catalog?q=перчатки');
    const list = await results();
    const gloves = within(list).getByRole('link', { name: 'Перчатки нитриловые, размер L' }).closest('article') as HTMLElement;
    expect(within(gloves).getByText('В наличии')).toBeInTheDocument();
    expect(within(gloves).queryByText(/срок/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 дн/)).not.toBeInTheDocument();
    await user.click(within(gloves).getByRole('link', { name: 'Перчатки нитриловые, размер L' }));
    await heading('Перчатки нитриловые, размер L');
    expect(screen.queryByText(/срок/)).not.toBeInTheDocument();
  });

  it('пагинация — в адресе страницы', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/catalog');
    await results();
    expect(screen.getByText('Страница 1 из 2')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Вперёд' }));
    expect(await screen.findByText('Страница 2 из 2')).toBeInTheDocument();
    // Поиск роли по списку, а не по всему документу: по документу jsdom тратит на это больше секунды
    expect(await within(await results()).findByRole('link', { name: 'Задвижка 30с41нж Ду100' })).toBeInTheDocument();
    expect(router.state.location.search).toBe('?page=2');
  });

  it('поиск и категории — в адресе страницы', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/catalog');
    await results();
    // Вставка, а не посимвольный ввод: каждое нажатие перерисовывает 12 карточек, на раннере CI это десятки секунд
    await user.click(screen.getByRole('searchbox', { name: 'Поиск по каталогу' }));
    await user.paste('ремень');
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
    expect(screen.getByText('165 000 сум')).toBeInTheDocument();
    await expectNoAxeViolations();
    await user.click(screen.getByRole('button', { name: 'Запросить' }));
    await heading('Новый запрос');
    expect(router.state.location.pathname).toBe('/requests/new');
    expect(screen.getByLabelText('Строка 1')).toHaveValue('Подшипник 6205-2RS');
    expect(screen.getByLabelText('Единица')).toHaveValue('шт');
    expect(screen.getByLabelText('Что нужно')).toHaveValue('Нужна позиция из каталога: Подшипник 6205-2RS');
  });

  // CAT-CARD-2: изготовитель, артикул, страна, гарантия, документы со скачиванием, галерея.
  it('карточка: изготовитель, артикул, страна происхождения, гарантия и действующие документы', async () => {
    signedIn();
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/catalog/1001');
    await heading('Подшипник 6205-2RS');
    const manufacturer = (await screen.findByRole('heading', { name: 'Изготовитель' })).closest('section') as HTMLElement;
    expect(within(manufacturer).getByText('Beispiel Wälzlager GmbH')).toBeInTheDocument();
    expect(within(manufacturer).getByText('Страна изготовителя')).toBeInTheDocument();
    expect(within(manufacturer).getByText('6205-2RS-C3')).toBeInTheDocument();
    expect(within(manufacturer).getByText('Страна происхождения')).toBeInTheDocument();
    expect(within(manufacturer).getByText('Китай')).toBeInTheDocument();

    const warranty = screen.getByRole('heading', { name: 'Гарантия' }).closest('section') as HTMLElement;
    expect(within(warranty).getByText('18 месяцев')).toBeInTheDocument();
    expect(within(warranty).getByText(/при соблюдении условий хранения/)).toBeInTheDocument();

    const documents = screen.getByRole('heading', { name: 'Документы' }).closest('section') as HTMLElement;
    expect(within(documents).getAllByRole('listitem')).toHaveLength(2);
    expect(within(documents).getByText('Сертификат соответствия')).toBeInTheDocument();
    expect(within(documents).getByText(/№ ТС RU C-DE\.АБ12\.В\.00345/)).toBeInTheDocument();
    expect(within(documents).getByText(/Выдан: Орган по сертификации «Эталон»/)).toBeInTheDocument();
    expect(within(documents).getByText(/Действует до 11 мар\. 2028/)).toBeInTheDocument();
    expect(within(documents).getByText('Бессрочно')).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('документ карточки скачивается кнопкой «Скачать»', async () => {
    signedIn();
    const user = userEvent.setup();
    vi.mocked(window.URL.createObjectURL).mockClear();
    renderApp('/catalog/1001');
    await user.click(await screen.findByRole('button', { name: 'Скачать: Паспорт подшипника 6205-2RS' }));
    await vi.waitFor(() => expect(window.URL.createObjectURL).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole('button', { name: 'Скачать: Паспорт подшипника 6205-2RS' })).toBeEnabled();
  });

  it('пустые блоки не рисуются: страна происхождения = страна изготовителя, документов и артикула нет', async () => {
    signedIn();
    renderApp('/catalog/1002');
    await heading('Ремень приводной SPZ 1250');
    const manufacturer = (await screen.findByRole('heading', { name: 'Изготовитель' })).closest('section') as HTMLElement;
    expect(within(manufacturer).getByText('Gürtel Antriebstechnik')).toBeInTheDocument();
    expect(within(manufacturer).queryByText('Страна происхождения')).not.toBeInTheDocument();
    expect(within(manufacturer).queryByText('Артикул изготовителя')).not.toBeInTheDocument();
    expect(screen.getByText('6 месяцев')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Документы' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Следующее фото' }), 'одно фото — без листания').not.toBeInTheDocument();
  });

  it('карточка без данных: ни изготовителя, ни гарантии, ни документов, ни фото', async () => {
    signedIn();
    renderApp('/catalog/1003');
    await heading('Пусконаладка насосного оборудования');
    for (const name of ['Изготовитель', 'Гарантия', 'Документы', 'Фотографии']) {
      expect(screen.queryByRole('heading', { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole('region', { name: 'Фотографии' })).not.toBeInTheDocument();
  });

  it('галерея: главное фото крупно, миниатюры, стрелки переключают, подписи фото', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/catalog/1001');
    await heading('Подшипник 6205-2RS');
    const gallery = await screen.findByRole('region', { name: 'Фотографии' });
    expect(within(gallery).getByRole('img', { name: 'Подшипник 6205-2RS, фото 1 из 3' })).toBeInTheDocument();
    const first = within(gallery).getByRole('button', { name: 'Фото 1 из 3' });
    expect(first).toHaveAttribute('aria-pressed', 'true');
    first.focus();
    await user.keyboard('{ArrowRight}');
    expect(within(gallery).getByRole('img', { name: 'Подшипник 6205-2RS, фото 2 из 3' })).toBeInTheDocument();
    const second = within(gallery).getByRole('button', { name: 'Фото 2 из 3' });
    expect(second).toHaveAttribute('aria-pressed', 'true');
    expect(second).toHaveFocus();
    await user.keyboard('{End}');
    expect(within(gallery).getByRole('img', { name: 'Подшипник 6205-2RS, фото 3 из 3' })).toBeInTheDocument();
    await user.keyboard('{ArrowRight}');
    expect(within(gallery).getByRole('img', { name: 'Подшипник 6205-2RS, фото 1 из 3' }), 'по кругу').toBeInTheDocument();
    await user.click(within(gallery).getByRole('button', { name: 'Следующее фото' }));
    expect(within(gallery).getByRole('img', { name: 'Подшипник 6205-2RS, фото 2 из 3' })).toBeInTheDocument();
  });

  it('список каталога не несёт документов (они только в детальной карточке)', async () => {
    signedIn();
    renderApp('/catalog');
    await results();
    expect(screen.queryByText('Сертификат соответствия')).not.toBeInTheDocument();
  });

  it('на английском и узбекском блоки подписаны на языке клиента', async () => {
    signedIn();
    renderApp('/catalog/1001');
    await heading('Подшипник 6205-2RS');
    await act(() => i18n.changeLanguage('en'));
    expect(await screen.findByRole('heading', { name: 'Manufacturer' })).toBeInTheDocument();
    expect(screen.getByText('Manufacturer part number')).toBeInTheDocument();
    expect(screen.getByText('18 months')).toBeInTheDocument();
    expect(screen.getByText('No expiry date')).toBeInTheDocument();
    await act(() => i18n.changeLanguage('uz'));
    expect(await screen.findByRole('heading', { name: 'Ishlab chiqaruvchi' })).toBeInTheDocument();
    expect(screen.getByText('Muddatsiz')).toBeInTheDocument();
    expect(screen.getByText('18 oy')).toBeInTheDocument();
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
