import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import i18n from '@/i18n';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading, requestLog } from '@/test/screens';

/** «Мои товары» партнёра (PART-2): вкладки, свои цены, отправка на проверку, подтверждение актуальности, карточка. */

const PARTNER = { roles: ['partner' as const], modules: ['my_products', 'catalog_requests', 'profile'] };

const list = () => screen.findByRole('list', { name: 'Мои карточки' });
const card = async (name: string) => (await within(await list()).findByText(name)).closest('li') as HTMLElement;

async function open(path = '/my-products', who: 'actor' | 'viewer' = 'actor', dataset: 'demo' | 'empty' = 'demo') {
  signedIn(who, dataset, PARTNER);
  const view = renderApp(path);
  await heading('Мои товары');
  return view;
}

describe('Мои товары: список', () => {
  it('вкладки с количеством, свои карточки со своей ценой и статусом', async () => {
    await open();
    const tabs = await screen.findByRole('group', { name: 'Статусы карточек' });
    expect(within(tabs).getByRole('button', { name: 'Все 8' })).toHaveAttribute('aria-pressed', 'true');
    for (const name of ['Черновики 3', 'На проверке 1', 'Возвращены 1', 'Опубликованы 2', 'Сопоставлены 1']) {
      expect(within(tabs).getByRole('button', { name })).toBeInTheDocument();
    }
    const pads = await card('Тормозная колодка композитная');
    expect(within(pads).getByText('Черновик')).toBeInTheDocument();
    expect(within(pads).getByText(/150,50/)).toBeInTheDocument();
    expect(within(pads).getByText(/Подтверждена/)).toBeInTheDocument();
    expect(within(pads).getByText('100 %')).toBeInTheDocument();
  });

  it('пометки: устарела, скоро истекает, срок истёк, есть изменение на проверке', async () => {
    await open();
    expect(within(await card('Подшипник 6205-2RS')).getByText('Цена устарела')).toBeInTheDocument();
    expect(within(await card('Фильтр масляный')).getByText('Срок скоро истекает')).toBeInTheDocument();
    expect(within(await card('Гайка М12')).getByText('Срок цены истёк')).toBeInTheDocument();
    expect(within(await card('Болт М12×60 оцинкованный')).getByText('Есть изменение на проверке')).toBeInTheDocument();
    const alert = await screen.findByText('Цены требуют внимания');
    expect(alert.closest('[role="alert"]')).toHaveTextContent('Устарело: 1. Срок истёк: 1. Скоро истекает: 1.');
  });

  it('возвращённая карточка: причина и подсвеченные поля', async () => {
    await open();
    const cable = await card('Кабель силовой 3×2,5');
    expect(within(cable).getByText('Возвращена')).toBeInTheDocument();
    expect(within(cable).getByText(/Причина возврата: Не указан артикул производителя/)).toBeInTheDocument();
    expect(within(cable).getByText(/Артикул производителя, Категория/)).toBeInTheDocument();
  });

  it('вкладка и поиск — в адресе страницы', async () => {
    const user = userEvent.setup();
    const { router } = await open();
    await user.click(await screen.findByRole('button', { name: 'Возвращены 1' }));
    expect(router.state.location.search).toBe('?tab=returned');
    await waitFor(() => expect(within(screen.getByRole('list', { name: 'Мои карточки' })).getAllByRole('listitem')).toHaveLength(1));
    await user.click(screen.getByRole('button', { name: 'Все 8' }));
    // вкладка применилась — только потом поиск (быстрые действия подряд покрывает тест «два действия подряд» ниже)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Все 8' })).toHaveAttribute('aria-pressed', 'true'));
    await user.type(screen.getByRole('searchbox'), 'гайка{Enter}');
    await waitFor(() => expect(decodeURIComponent(router.state.location.search)).toContain('q=гайка'));
    await waitFor(() => {
      // не просто «одна строка»: она могла остаться от вкладки «Возвращены», пока список «Все» ещё не перечитан
      const rows = within(screen.getByRole('list', { name: 'Мои карточки' })).getAllByRole('listitem');
      expect(rows).toHaveLength(1);
      expect(within(rows[0]).getByText('Гайка М12')).toBeInTheDocument();
    });
    expect(router.state.location.search).toContain('q=');
  });

  it('два быстрых действия подряд — вкладка и поиск — не затирают друг друга в адресе', async () => {
    const user = userEvent.setup();
    const { router } = await open();
    await screen.findByRole('button', { name: 'Возвращены 1' });
    // без ожидания между действиями: так нажимает человек; раньше второе обновление адреса теряло первое
    await user.click(screen.getByRole('button', { name: 'Возвращены 1' }));
    await user.type(screen.getByRole('searchbox'), 'кабель{Enter}');
    await waitFor(() => {
      const search = new URLSearchParams(router.state.location.search);
      expect(search.get('tab')).toBe('returned');
      expect(search.get('q')).toBe('кабель');
    });
    await waitFor(() => {
      const rows = within(screen.getByRole('list', { name: 'Мои карточки' })).getAllByRole('listitem');
      expect(rows).toHaveLength(1);
      expect(within(rows[0]).getByText('Кабель силовой 3×2,5')).toBeInTheDocument();
    });
  });

  it('чужую карточку с моей ценой можно выбрать только для подтверждения цены, на проверку — нельзя', async () => {
    const user = userEvent.setup();
    await open();
    const foreign = await card('Уплотнитель дверной');
    expect(within(foreign).getByText('Сопоставлено с карточкой каталога')).toBeInTheDocument();
    expect(within(foreign).getByText('Аквилон · SEAL-D1')).toBeInTheDocument(); // только присланное партнёром
    await user.click(within(foreign).getByRole('checkbox'));
    expect(await screen.findByRole('button', { name: 'Подтвердить выбранные цены (1)' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Отправить на проверку/ })).not.toBeInTheDocument();
  });

  it('публикации в кабинете нет: ни кнопки, ни пункта', async () => {
    await open();
    await list();
    expect(screen.queryByText(/Опубликовать/)).not.toBeInTheDocument();
  });

  it('axe: список без нарушений', async () => {
    await open();
    await list();
    await expectNoAxeViolations();
  });
});

describe('Мои товары: карточка', () => {
  it('открывается по названию: данные, подсветка поля с замечанием, история проверок', async () => {
    const user = userEvent.setup();
    const { router } = await open();
    await user.click(within(await card('Кабель силовой 3×2,5')).getByRole('button', { name: /Открыть карточку/ }));
    const dialog = await screen.findByRole('dialog');
    expect(router.state.location.search).toBe('?card=9005');
    expect((await within(dialog).findAllByText('Укажите артикул по шильдику изделия')).length).toBeGreaterThan(0);
    expect(dialog.querySelector('[data-issue="manufacturer_part_number"]')).not.toBeNull();
    expect(dialog.querySelector('[data-issue="category"]')).not.toBeNull();
    expect(within(dialog).getByText('Общий комментарий:')).toBeInTheDocument();
    expect(within(dialog).getByText('История проверок')).toBeInTheDocument();
    expect(within(dialog).getAllByText('Возвращена').length).toBeGreaterThan(0);
    await expectNoAxeViolations();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(router.state.location.search).toBe(''));
  });

  it('чужая карточка открывается без истории, с пояснением', async () => {
    const user = userEvent.setup();
    await open();
    await user.click(within(await card('Уплотнитель дверной')).getByRole('button', { name: /Открыть карточку/ }));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText(/Ваша цена сопоставлена с карточкой каталога/)).toBeInTheDocument();
    // чужие поля не рисуются совсем: ни категории, ни описания, ни ТН ВЭД
    for (const label of ['Категория', 'Описание', 'Код ТН ВЭД', 'Единица измерения']) {
      expect(within(dialog).queryByText(label)).not.toBeInTheDocument();
    }
    expect(within(dialog).queryByText('История проверок')).not.toBeInTheDocument();
  });

  it('карточка из адреса, которой нет, — ошибка «не найдено» без намёка на чужие данные', async () => {
    signedIn('actor', 'demo', PARTNER);
    renderApp('/my-products?card=999');
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Не найдено.')).toBeInTheDocument();
  });
});

describe('Мои товары: отправка на проверку', () => {
  it('выбранный черновик → диалог → «На проверке» и срок проверки', async () => {
    const user = userEvent.setup();
    await open();
    const log = requestLog();
    await user.click(within(await card('Тормозная колодка композитная')).getByRole('checkbox'));
    await user.click(await screen.findByRole('button', { name: 'Отправить на проверку (1)' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Отправляем 1 карточку.')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Отправить' }));
    expect(await screen.findByText('Отправлена 1 карточка')).toBeInTheDocument();
    expect(screen.getByText(/Проверка обычно занимает 1 рабочий день/)).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByRole('group', { name: 'Статусы карточек' })).getByRole('button', { name: 'На проверке 2' })).toBeInTheDocument());
    expect(log).toContain('POST /partner/products/submit');
    expect(within(await card('Тормозная колодка композитная')).getByText('На проверке')).toBeInTheDocument();
  });

  it('«Отправить все черновики» собирает черновики всех страниц', async () => {
    const user = userEvent.setup();
    await open();
    await user.click(await screen.findByRole('button', { name: 'Отправить все черновики (3)' }));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Отправляем 3 карточки.')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Отправить' }));
    expect(await screen.findByText('Отправлено 3 карточки')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'На проверке 4' })).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Отправить все черновики/ })).not.toBeInTheDocument();
  });

  it('возвращённую карточку можно выбрать и отправить снова', async () => {
    const user = userEvent.setup();
    await open();
    await user.click(within(await card('Кабель силовой 3×2,5')).getByRole('checkbox'));
    await user.click(await screen.findByRole('button', { name: 'Отправить на проверку (1)' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Отправить' }));
    expect(await screen.findByText('Отправлена 1 карточка')).toBeInTheDocument();
    expect(within(await card('Кабель силовой 3×2,5')).getByText('На проверке')).toBeInTheDocument();
  });
});

describe('Мои товары: подтвердить актуальность', () => {
  it('выбранные цены: подтверждаются без модерации, «устарела» уходит', async () => {
    const user = userEvent.setup();
    await open();
    await user.click(within(await card('Подшипник 6205-2RS')).getByRole('checkbox'));
    await user.click(await screen.findByRole('button', { name: 'Подтвердить выбранные цены (1)' }));
    expect(await screen.findByText('Подтверждена 1 цена')).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByText('Подшипник 6205-2RS').closest('li') as HTMLElement).queryByText('Цена устарела')).not.toBeInTheDocument());
  });

  it('«Подтвердить все цены»: цена с истёкшим сроком не подтверждается и об этом сказано', async () => {
    const user = userEvent.setup();
    await open();
    await user.click(await screen.findByRole('button', { name: 'Подтвердить все цены' }));
    expect(await screen.findByText('Подтверждено 7 цен')).toBeInTheDocument();
    expect(screen.getByText(/Не подтверждено из-за истёкшего срока: 1/)).toBeInTheDocument();
    expect(within(await card('Гайка М12')).getByText('Срок цены истёк')).toBeInTheDocument();
  });
});

describe('Мои товары: права и пустой раздел', () => {
  it('без права действовать: список виден, кнопок загрузки, отправки и подтверждения нет', async () => {
    window.localStorage.setItem('cabinet.language', 'ru'); // явный выбор перекрывает язык контакта (у наблюдателя мока — uz)
    await open('/my-products', 'viewer');
    await list();
    expect(screen.queryByRole('button', { name: 'Загрузить прайс' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Отправить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Подтвердить/ })).not.toBeInTheDocument();
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Скачать шаблон' })).toBeInTheDocument(); // шаблон доступен и для просмотра
  });

  it('пустой раздел: «Загрузите прайс по шаблону» и три шага с кнопками', async () => {
    const user = userEvent.setup();
    await open('/my-products', 'actor', 'empty');
    expect(await screen.findByRole('heading', { name: 'Загрузите прайс по шаблону — карточки появятся здесь' })).toBeInTheDocument();
    const steps = screen.getByRole('list', { name: 'Как загрузить прайс' });
    expect(within(steps).getAllByRole('listitem')).toHaveLength(3);
    for (const title of ['Скачать шаблон', 'Заполнить', 'Загрузить']) {
      expect(within(steps).getByRole('heading', { name: new RegExp(title) })).toBeInTheDocument();
    }
    expect(within(steps).getByRole('button', { name: 'Скачать шаблон' })).toBeInTheDocument();
    await user.click(within(steps).getByRole('button', { name: 'Загрузить прайс' }));
    expect(await screen.findByRole('dialog', { name: 'Загрузка прайса' })).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('клиент без модуля «Мои товары» раздел не открывает — возврат в его первый раздел', async () => {
    signedIn();
    const { router } = renderApp('/my-products');
    await waitFor(() => expect(router.state.location.pathname).toBe('/requests'));
  });

  it('английский: заголовок, вкладки, статусы и кнопки без русских подписей', async () => {
    window.localStorage.setItem('cabinet.language', 'en'); // явный выбор перекрывает язык контакта из /me
    await i18n.changeLanguage('en'); // сбрасывается на ru перед каждым тестом (setup.ts)
    signedIn('actor', 'demo', PARTNER);
    renderApp('/my-products');
    await heading('My products');
    expect(await screen.findByRole('button', { name: 'All 8' })).toBeInTheDocument();
    const cards = await screen.findByRole('list', { name: 'My cards' });
    expect(within((await within(cards).findByText('Втулка резиновая')).closest('li') as HTMLElement).getByText('In review')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upload price list' })).toBeInTheDocument();
  });
});
