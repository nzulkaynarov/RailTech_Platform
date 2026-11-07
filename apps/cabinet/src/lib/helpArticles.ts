export interface HelpArticle {
  id: string;
  category: 'general' | 'quotes' | 'billing' | 'deliveries' | 'products' | 'team' | 'profile' | 'messages';
  routePatterns: string[];
  title: {
    ru: string;
    uz: string;
    en: string;
  };
  summary: {
    ru: string;
    uz: string;
    en: string;
  };
  content: {
    ru: string[];
    uz: string[];
    en: string[];
  };
}

export const HELP_ARTICLES: HelpArticle[] = [
  {
    id: 'quotes-accept',
    category: 'quotes',
    routePatterns: ['/', '/quotes'],
    title: {
      ru: 'Как согласовать или отклонить коммерческое предложение (КП)?',
      uz: 'Tijorat taklifini (TT) qanday tasdiqlash yoki rad etish mumkin?',
      en: 'How to accept or reject a commercial quote?',
    },
    summary: {
      ru: 'Порядок подтверждения КП одноразовым кодом из SMS/Telegram/E-mail.',
      uz: 'Bir martalik kod orqali tijorat taklifini tasdiqlash tartibi.',
      en: 'Procedure for confirming a quote via one-time code.',
    },
    content: {
      ru: [
        'Откройте карточку нужного коммерческого предложения в разделе «КП».',
        'Если у вас есть право подписи (can_act), внизу будут активны кнопки «Принять КП» и «Отклонить».',
        'При нажатии «Принять КП» вам будет направлен одноразовый 6-значный код (в Telegram или на почту). Введите его в поле подтверждения.',
        'После ввода кода КП переходит в статус «Принято», и формируется проект договора.',
      ],
      uz: [
        '«TT» bo‘limida kerakli tijorat taklifi kartochkasini oching.',
        'Agar sizda tasdiqlash huquqi (can_act) bo‘lsa, pastda «TTni qabul qilish» va «Rad etish» tugmalari faol bo‘ladi.',
        '«TTni qabul qilish» tugmasi bosilganda Telegram yoki pochtangizga 6 xonali tasdiqlash kodi yuboriladi.',
        'Kod kiritilgach, taklif «Qabul qilindi» holatiga o‘tadi va shartnoma loyihasi tayyorlanadi.',
      ],
      en: [
        'Open the commercial quote in the "Quotes" section.',
        'If you have approval permissions (can_act), the "Accept" and "Reject" buttons will be available.',
        'Clicking "Accept" will send a one-time 6-digit confirmation code via Telegram or email.',
        'Once entered, the quote status changes to "Accepted", and a draft contract is initiated.',
      ],
    },
  },
  {
    id: 'contracts-eds',
    category: 'billing',
    routePatterns: ['/billing', '/contracts'],
    title: {
      ru: 'Электронная подпись (ЭЦП / EDS) и согласование договоров',
      uz: 'Elektron raqamli imzo (ERI / EDS) va shartnomalarni tasdiqlash',
      en: 'Digital signature (EDS) and contract approvals',
    },
    summary: {
      ru: 'Как подписывать договоры и акты с помощью E-IMZO / ЭЦП.',
      uz: 'E-IMZO orqali shartnoma va dalolatnomalarni imzolash.',
      en: 'How to sign contracts and acceptance acts using EDS.',
    },
    content: {
      ru: [
        'В разделе «Договоры» или «Акты» выберите документ со статусом «Ожидает подписания».',
        'Нажмите «Подписать ЭЦП». Убедитесь, что модуль E-IMZO запущен на вашем компьютере.',
        'Выберите ключ вашей организации и введите пароль контейнера ключа.',
        'После успешного подписания статус документа автоматически обновится на «Подписан».',
      ],
      uz: [
        '«Shartnomalar» yoki «Dalolatnomalar» bo‘limida «Imzolash kutilmoqda» holatidagi hujjatni tanlang.',
        '«ERI bilan imzolash» tugmasini bosing. Kompyuteringizda E-IMZO moduli ishlayotganiga ishonch hosil qiling.',
        'Tashkilotingiz kalitini tanlang va parolni kiriting.',
        'Muvaffaqiyatli imzolangach, hujjat holati avtomatik tarzda «Imzolandi»ga o‘zgaradi.',
      ],
      en: [
        'In the "Contracts" or "Acts" section, select a document pending signature.',
        'Click "Sign with EDS". Ensure the local E-IMZO module is running.',
        'Select your organization certificate and enter key password.',
        'Upon successful signing, the document status will update to "Signed".',
      ],
    },
  },
  {
    id: 'invoices-payment',
    category: 'billing',
    routePatterns: ['/billing', '/invoices'],
    title: {
      ru: 'Оплата счетов и финансовые документы',
      uz: 'Hisoblarni to‘lash va moliyaviy hujjatlar',
      en: 'Invoice payments and billing documents',
    },
    summary: {
      ru: 'Где скачать счет на оплату и как отслеживать поступление денег.',
      uz: 'To‘lov hisob-fakturasini yuklab olish va to‘lovlarni kuzatish.',
      en: 'Downloading invoices and tracking incoming payments.',
    },
    content: {
      ru: [
        'Счета на оплату формируются автоматически после согласования договора или заказа.',
        'Вы можете скачать официальный PDF счета с реквизитами и QR-кодом для быстрой оплаты.',
        'После фактического зачисления средств в банк статус счета изменится на «Оплачен», а вы получите уведомление.',
      ],
      uz: [
        'To‘lov hisoblari shartnoma tasdiqlangandan so‘ng avtomatik tarzda yaratiladi.',
        'To‘lov rekvizitlari va QR-kodli rasmiy PDF hisobni yuklab olishingiz mumkin.',
        'Mablag‘ bankka kelib tushgach, hisob holati «To‘langan»ga aylanadi va sizga xabarnoma yuboriladi.',
      ],
      en: [
        'Invoices are generated automatically following contract approval.',
        'You can download official PDF invoices with banking details and QR code.',
        'Once funds settle in our bank account, the invoice status changes to "Paid" with instant notification.',
      ],
    },
  },
  {
    id: 'deliveries-tracking',
    category: 'deliveries',
    routePatterns: ['/deliveries'],
    title: {
      ru: 'Отслеживание доставки и отгрузок',
      uz: 'Yetkazib berish va jo‘natmalarni kuzatish',
      en: 'Shipment and delivery tracking',
    },
    summary: {
      ru: 'Контроль этапов комплектации, отправки и поступления на склад.',
      uz: 'Yetkazib berish bosqichlari va omborga kelib tushish nazorati.',
      en: 'Monitoring fulfillment, transit, and warehouse delivery.',
    },
    content: {
      ru: [
        'Раздел «Поставки» содержит подробную информацию обо всех отгрузках по вашим заказам.',
        'Для каждой поставки отображаются текущий статус, ориентировочная дата прибытия и список позиций.',
        'При изменении статуса доставки (отправлено, прибыло) вам поступит уведомление в выбранные каналы связи.',
      ],
      uz: [
        '«Yetkazib berish» bo‘limida barcha jo‘natmalar bo‘yicha to‘liq ma‘lumot mavjud.',
        'Har bir yetkazib berish uchun joriy holat, yetib kelish sanasi va tovarlar ro‘yxati ko‘rsatiladi.',
        'Holat o‘zgarganda (jo‘natildi, yetib keldi) belgilangan aloqa kanallariga xabar yuboriladi.',
      ],
      en: [
        'The "Deliveries" section displays all shipments associated with your orders.',
        'Each delivery specifies current status, estimated arrival, and line items.',
        'Status transitions trigger notifications to your configured channels.',
      ],
    },
  },
  {
    id: 'team-and-security',
    category: 'team',
    routePatterns: ['/company', '/team'],
    title: {
      ru: 'Управление командой и защита банковских реквизитов',
      uz: 'Jamoani boshqarish va bank rekvizitlari xavfsizligi',
      en: 'Team management and bank requisites protection',
    },
    summary: {
      ru: 'Приглашение сотрудников, роли и ограничение изменения реквизитов.',
      uz: 'Xodimlarni taklif qilish va rekvizitlar o‘zgarishini cheklash.',
      en: 'Inviting colleagues, roles, and requisites change restrictions.',
    },
    content: {
      ru: [
        'Администратор компании может приглашать коллег в разделе «Команда».',
        'Роли определяют возможности: просмотр, право подписи (can_act) и администратор (is_admin).',
        'Важно: банковские реквизиты компании может изменять только администратор. При любом изменении все администраторы немедленно получают предупреждение безопасности.',
      ],
      uz: [
        'Kompaniya administratori «Jamoa» bo‘limida xodimlarni taklif qilishi mumkin.',
        'Rollar huquqlarni belgilaydi: ko‘rish, imzolash huquqi (can_act) va administrator (is_admin).',
        'Muhim: bank rekvizitlarini faqat administrator o‘zgartirishi mumkin. O‘zgartirilganda barcha administratorlarga xavfsizlik ogohlantirishi boradi.',
      ],
      en: [
        'Company administrators can invite colleagues in the "Team" section.',
        'Roles specify privileges: view only, action rights (can_act), and administrator (is_admin).',
        'Important: only administrators can modify banking details. Any edit triggers security alerts to all company admins.',
      ],
    },
  },
  {
    id: 'profile-notifications-channels',
    category: 'profile',
    routePatterns: ['/profile'],
    title: {
      ru: 'Каналы уведомлений и привязка Telegram',
      uz: 'Xabarnomalar kanallari va Telegramni ulash',
      en: 'Notification channels and Telegram binding',
    },
    summary: {
      ru: 'Настройка получения оповещений в Telegram, E-mail и кабинет.',
      uz: 'Telegram, E-mail va kabinetda bildirishnomalarni sozlash.',
      en: 'Configuring Telegram, Email, and in-app notifications.',
    },
    content: {
      ru: [
        'В разделе «Профиль» подключите официального Telegram-бота для мгновенных уведомлений и быстрого входа без пароля.',
        'В матрице «Каналы уведомлений» вы можете настроить, какие категории событий (документы, финансы, доставка, сообщения) отправлять на почту или в Telegram.',
        'Оповещения безопасности (вход с нового устройства, изменение реквизитов) обязательны и доставляются во все доступные каналы.',
      ],
      uz: [
        '«Profil» bo‘limida tezkor xabarlar va parolsiz kirish uchun Telegram botni ulang.',
        '«Xabarnoma kanallari» jadvalida qaysi voqealar (hujjatlar, moliya, yetkazib berish) qaysi kanalga borishini tanlang.',
        'Xavfsizlik ogohlantirishlari barcha ulangan kanallarga majburiy yuboriladi.',
      ],
      en: [
        'In "Profile", link the Telegram bot for instant alerts and passwordless login.',
        'Use the Notification Channels matrix to select event groups (documents, money, deliveries, messages) for Email or Telegram.',
        'Security notices are always dispatched to all available channels.',
      ],
    },
  },
  {
    id: 'partner-products-guide',
    category: 'products',
    routePatterns: ['/my-products'],
    title: {
      ru: '«Мои товары» — публикация каталога для партнёров',
      uz: '«Mening mahsulotlarim» — hamkorlar uchun tovarlar katalogi',
      en: 'Partner Products — catalog management for suppliers',
    },
    summary: {
      ru: 'Загрузка прайс-листов, модерация карточек и контроль цен.',
      uz: 'Narxlar ro‘yxatini yuklash, kartochkalar moderatsiyasi va narxlarni boshqarish.',
      en: 'Price-list upload, card moderation, and inventory management.',
    },
    content: {
      ru: [
        'Партнёры платформы могут поставлять собственную продукцию через платформу RailTech.',
        'Загрузите файл Excel по стандартному шаблону через «Загрузить прайс-лист».',
        'После загрузки карточки проходят автоматическую и ручную модерацию перед публикацией в общем каталоге.',
      ],
      uz: [
        'Platforma hamkorlari o‘z mahsulotlarini RailTech orqali yetkazib berishlari mumkin.',
        '«Narxlar ro‘yxatini yuklash» orqali standart Excel faylini yuklang.',
        'Yuklangach, tovar kartochkalari umumiy katalogda chop etilishidan oldin moderatsiyadan o‘tadi.',
      ],
      en: [
        'Verified partners can distribute their products through the RailTech platform.',
        'Upload your Excel catalog using the standard template.',
        'Cards undergo automatic and manual verification before public catalog listing.',
      ],
    },
  },
  {
    id: 'messages-support',
    category: 'messages',
    routePatterns: ['/messages'],
    title: {
      ru: 'Чат с персональным менеджером RailTech',
      uz: 'RailTech shaxsiy menejeri bilan muloqot',
      en: 'Chat with your RailTech manager',
    },
    summary: {
      ru: 'Прямая связь со специалистом, отправка вложений и архив переписки.',
      uz: 'Mutaxassis bilan to‘g‘ridan-to‘g‘ri aloqa va yozishmalar tarixi.',
      en: 'Direct messaging with manager and file attachments.',
    },
    content: {
      ru: [
        'В разделе «Сообщения» доступен прямой диалог с закреплённым за вашей компанией менеджером.',
        'Вы можете задавать любые вопросы по поставкам, спецификациям или документам, а также прикреплять файлы.',
        'Ответы менеджера дублируются в ваш подключённый Telegram и на электронную почту.',
      ],
      uz: [
        '«Xabarlar» bo‘limida sizga biriktirilgan menejer bilan to‘g‘ridan-to‘g‘ri muloqot qilishingiz mumkin.',
        'Yetkazib berish, tovarlar yoki hujjatlar bo‘yicha savollaringizni yozishingiz va fayllar biriktirishingiz mumkin.',
        'Menejer javoblari Telegram va elektron pochtangizga ham yetkaziladi.',
      ],
      en: [
        'The "Messages" section provides a direct line to your dedicated account manager.',
        'Ask questions regarding deliveries, specifications, or contracts, and attach files.',
        'Replies are forwarded directly to your linked Telegram and email.',
      ],
    },
  },
];

export function getArticlesForRoute(pathname: string): HelpArticle[] {
  const normalized = pathname.toLowerCase();
  const matched = HELP_ARTICLES.filter((article) =>
    article.routePatterns.some((pattern) => {
      if (pattern === '/') return normalized === '/' || normalized === '';
      return normalized.startsWith(pattern);
    }),
  );
  if (matched.length > 0) return matched;
  return HELP_ARTICLES.slice(0, 3);
}

export function searchHelpArticles(query: string, lang: 'ru' | 'uz' | 'en'): HelpArticle[] {
  const q = query.trim().toLowerCase();
  if (!q) return HELP_ARTICLES;

  return HELP_ARTICLES.filter((article) => {
    const title = article.title[lang].toLowerCase();
    const summary = article.summary[lang].toLowerCase();
    const content = article.content[lang].join(' ').toLowerCase();
    return title.includes(q) || summary.includes(q) || content.includes(q);
  });
}

