import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { setMockPartnerApplication, setMockSession } from '@/mocks/handlers';
import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, heading } from '@/test/screens';

describe('Онбординг партнёров (PART-ONBOARD-1)', () => {
  beforeEach(() => {
    window.localStorage.setItem('cabinet.language', 'ru');
  });

  afterEach(() => {
    setMockPartnerApplication(null);
    setMockSession(null);
    window.localStorage.removeItem('cabinet.language');
  });

  describe('Вход: карточка «Стать партнёром» на странице логина', () => {
    it('отображает блок поставщикам со ссылкой на /become-partner', async () => {
      renderApp('/login');
      await heading('Вход в кабинет');

      expect(screen.getByText('Поставщикам и производителям')).toBeInTheDocument();
      const link = screen.getByRole('link', { name: /Стать партнёром/ });
      expect(link).toHaveAttribute('href', '/become-partner');
      await expectNoAxeViolations();
    });
  });

  describe('Публичная форма «Стать партнёром» (/become-partner)', () => {
    it('валидация обязательных полей формы', async () => {
      const user = userEvent.setup();
      renderApp('/become-partner');
      await heading('Заявка на партнёрство');

      // Попытка отправить пустую форму
      await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
      expect(screen.getByText('Укажите название компании.')).toBeInTheDocument();

      // Заполняем название компании
      await user.type(screen.getByLabelText('Название компании'), 'ООО «ПромРельс»');
      await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
      expect(screen.getByText('Укажите имя контактного лица.')).toBeInTheDocument();

      // Заполняем контактное лицо
      await user.type(screen.getByLabelText('Контактное лицо'), 'Александр Воронов');
      await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
      expect(screen.getByText('Введите корректный рабочий e-mail.')).toBeInTheDocument();

      // Заполняем e-mail
      await user.type(screen.getByLabelText('Рабочий e-mail'), 'voronov@promrails.uz');
      await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
      expect(screen.getByText('Опишите продукцию подробнее (минимум 10 символов).')).toBeInTheDocument();

      // Заполняем описание категорий
      await user.type(
        screen.getByLabelText('Поставляемая продукция и категории'),
        'Рельсовые накладки и стрелочные переводы',
      );
      await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
      expect(screen.getByText('Необходимо согласие на обработку персональных данных.')).toBeInTheDocument();
    });

    it('успешная отправка заявки и экран шагов шлюза договоров', async () => {
      const user = userEvent.setup();
      const body = captureBody('/auth/partner-application');
      renderApp('/become-partner');
      await heading('Заявка на партнёрство');

      await user.type(screen.getByLabelText('Название компании'), 'ООО «ПромРельс»');
      await user.type(screen.getByLabelText(/ИНН/), '123456789');
      // Переключаем тип на «Производитель»
      await user.click(screen.getByRole('button', { name: 'Производитель' }));
      await user.type(
        screen.getByLabelText('Поставляемая продукция и категории'),
        'Высоковольтные изоляторы для контактной сети',
      );
      await user.type(screen.getByLabelText('Контактное лицо'), 'Александр Воронов');
      await user.type(screen.getByLabelText('Рабочий e-mail'), 'voronov@promrails.uz');
      await user.type(screen.getByLabelText('Телефон'), '+998901234567');
      await user.click(screen.getByRole('checkbox', { name: /Я даю согласие/ }));

      await expectNoAxeViolations();

      await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));

      // Проверяем экран успешного приёма заявки
      expect(await heading('Заявка принята')).toBeInTheDocument();
      expect(screen.getByText(/Что происходит дальше\?/)).toBeInTheDocument();
      expect(screen.getByText('Проверка данных')).toBeInTheDocument();
      expect(screen.getByText('Подписание партнёрского договора')).toBeInTheDocument();
      expect(screen.getByText('Доступ к кабинету партнёра')).toBeInTheDocument();

      const backLink = screen.getByRole('link', { name: 'Вернуться ко входу' });
      expect(backLink).toHaveAttribute('href', '/login');

      // Проверяем отправленное тело
      expect(body.current).toMatchObject({
        company_name: 'ООО «ПромРельс»',
        inn: '123456789',
        kind: 'manufacturer',
        categories_description: 'Высоковольтные изоляторы для контактной сети',
        contact_name: 'Александр Воронов',
        email: 'voronov@promrails.uz',
        phone: '+998901234567',
        consent: true,
        website: '',
      });
    });

    it('поддержка нерезидентов: предзаполнение email из URL и отправка country с registration_number (COUNTRY-MASK-1)', async () => {
      const user = userEvent.setup();
      const body = captureBody('/auth/partner-application');
      renderApp('/become-partner?email=partner%40kazakh-rails.kz');
      await heading('Заявка на партнёрство');

      // Email предзаполнен из URL query параметра
      expect(screen.getByLabelText('Рабочий e-mail')).toHaveValue('partner@kazakh-rails.kz');

      // Выбираем страну Казахстан
      const countrySelect = screen.getByRole('combobox', { name: /Страна/ });
      await user.click(countrySelect);
      const kzOption = await screen.findByRole('option', { name: /Казахстан/ });
      await user.click(kzOption);

      await user.type(screen.getByLabelText('Название компании'), 'ТОО «Казахские Рельсы»');
      await user.type(screen.getByLabelText(/БИН/), '123456789012');
      await user.type(
        screen.getByLabelText('Поставляемая продукция и категории'),
        'Высокопрочные железнодорожные рельсы Р65',
      );
      await user.type(screen.getByLabelText('Контактное лицо'), 'Нурлан Сапаров');
      await user.type(screen.getByLabelText('Телефон'), '+77011234567');
      await user.click(screen.getByRole('checkbox', { name: /Я даю согласие/ }));

      await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
      expect(await heading('Заявка принята')).toBeInTheDocument();

      expect(body.current).toMatchObject({
        company_name: 'ТОО «Казахские Рельсы»',
        country: 'KZ',
        registration_number: '123456789012',
        kind: 'supplier',
        email: 'partner@kazakh-rails.kz',
        phone: '+77011234567',
        consent: true,
      });
    });

    it('срабатывание защиты honeypot', async () => {
      portalServer.use(
        http.post('*/api/portal/v1/auth/partner-application', () =>
          HttpResponse.json({ detail: 'HONEYPOT_DETECTED' }, { status: 400 }),
        ),
      );

      const user = userEvent.setup();
      renderApp('/become-partner');

      await user.type(screen.getByLabelText('Название компании'), 'Bot Corp');
      await user.type(screen.getByLabelText('Контактное лицо'), 'Spambot');
      await user.type(screen.getByLabelText('Рабочий e-mail'), 'bot@spamsite.com');
      await user.type(screen.getByLabelText('Поставляемая продукция и категории'), 'Automated spam products description');
      await user.click(screen.getByRole('checkbox', { name: /Я даю согласие/ }));

      await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
      expect(await screen.findByText('Обнаружена подозрительная активность формы.')).toBeInTheDocument();
    });
  });

  describe('Подача заявки в партнёры действующим клиентом (/company)', () => {
    it('клиент без заявки видит кнопку подачи заявки и успешно подаёт её через диалог', async () => {
      signedIn('actor');
      const user = userEvent.setup();
      const body = captureBody('/company/partner-application');

      renderApp('/company');
      await heading('Компания');

      // Блок «Партнёрская программа»
      expect(await screen.findByText('Партнёрская программа')).toBeInTheDocument();
      const applyBtn = screen.getByRole('button', { name: 'Подать заявку в партнёры' });
      expect(applyBtn).toBeInTheDocument();

      await user.click(applyBtn);

      // Диалог заявки
      const dialog = await screen.findByRole('dialog');
      expect(within(dialog).getByText('Заявка на статус партнёра')).toBeInTheDocument();

      // Переключаем тип на «Производитель» и вводим категории
      await user.click(within(dialog).getByRole('button', { name: 'Производитель' }));
      await user.type(
        within(dialog).getByLabelText('Поставляемая продукция и категории'),
        'Производство тормозных колодок для грузовых вагонов',
      );

      await expectNoAxeViolations();

      await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

      await waitFor(() => {
        expect(body.current).toEqual({
          kind: 'manufacturer',
          categories_description: 'Производство тормозных колодок для грузовых вагонов',
        });
      });
    });

    it('отображение заявки со статусом «На рассмотрении»', async () => {
      signedIn('actor');
      setMockPartnerApplication({
        id: 501,
        status: 'submitted',
        kind: 'supplier',
        categories_description: 'Комплектующие для локомотивов и дизелей',
        company_name: 'ООО Клиент',
        inn: '123456789',
        contact_name: 'Иван',
        email: 'ivan@example.uz',
        phone: null,
        contract_number: null,
        contract_date: null,
        rejected_reason: null,
        created_at: '2026-11-05T12:00:00Z',
        updated_at: '2026-11-05T12:00:00Z',
      });

      renderApp('/company');
      await heading('Компания');

      expect(await screen.findByText('На рассмотрении')).toBeInTheDocument();
      expect(screen.getByText('Заявка на получение статуса партнёра подана и находится на согласовании в RailTech.')).toBeInTheDocument();
      expect(screen.getByText('Комплектующие для локомотивов и дизелей')).toBeInTheDocument();
    });

    it('отображение заявки со статусом «Договор отправлен» и номером договора', async () => {
      signedIn('actor');
      setMockPartnerApplication({
        id: 502,
        status: 'contract_sent',
        kind: 'manufacturer',
        categories_description: 'Стрелочные электроприводы',
        company_name: 'ООО Клиент',
        inn: '123456789',
        contact_name: 'Иван',
        email: 'ivan@example.uz',
        phone: null,
        contract_number: 'PRT-2026-088',
        contract_date: '2026-11-05',
        rejected_reason: null,
        created_at: '2026-11-05T12:00:00Z',
        updated_at: '2026-11-05T14:00:00Z',
      });

      renderApp('/company');
      await heading('Компания');

      expect(await screen.findByText('Договор отправлен')).toBeInTheDocument();
      expect(screen.getByText('Партнёрский договор подготовлен и направлен на согласование вашей компании.')).toBeInTheDocument();
      expect(screen.getByText('PRT-2026-088 от 2026-11-05')).toBeInTheDocument();
    });

    it('компания уже имеет активный договор партнёра: карточка со ссылкой на «Мои товары»', async () => {
      signedIn('actor', 'demo', {
        roles: ['client', 'partner'],
        modules: ['company', 'my_products'],
      });

      renderApp('/company');
      await heading('Компания');

      expect(await screen.findByText('Партнёрский договор активен')).toBeInTheDocument();
      const myProductsLink = screen.getByRole('link', { name: 'Перейти в «Мои товары»' });
      expect(myProductsLink).toHaveAttribute('href', '/my-products');
    });

    it('пользователь без права подписи (can_act=false) не может подать заявку', async () => {
      signedIn('viewer');

      renderApp('/company');
      await heading('Компания');

      expect(await screen.findByText('Партнёрская программа')).toBeInTheDocument();
      expect(screen.getByText('Подать заявку может только представитель с правом подтверждать действия.')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Подать заявку в партнёры' })).not.toBeInTheDocument();
    });
  });
});
