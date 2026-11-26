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
    id: 'partner-contract',
    category: 'general',
    routePatterns: ['/company'],
    title: {
      ru: 'Партнёрский договор: прочитать, согласовать, вернуть, загрузить скан',
      uz: 'Hamkorlik şartnomasi: öqiş, kelişiş, qaytariş, skan yuklaş',
      en: 'Partner contract: read, agree, return, upload the scan',
    },
    summary: {
      ru: 'Что делать, когда мы отправили вам партнёрский договор.',
      uz: 'Sizga hamkorlik şartnomasi yuborilganda nima qiliş kerak.',
      en: 'What to do when we have sent you a partner contract.',
    },
    content: {
      ru: [
        'Откройте «Компания» — карточка «Партнёрский договор». Кнопка «Открыть договор» показывает файл, который мы отправили.',
        'Если всё устраивает, нажмите «Согласовать проект договора». Если нет — «Вернуть с замечанием» и напишите, что изменить: мы подготовим новую версию.',
        'После согласия подпишите договор и загрузите скан: «Загрузить скан» (PDF или изображение). Скан можно заменить.',
        'Когда мы подтвердим договор, в меню откроются разделы партнёра.',
        'Согласовать, вернуть и загрузить скан может представитель с правом подтверждать действия.',
      ],
      uz: [
        '«Kompaniya» böliminda «Hamkorlik şartnomasi» kartasini oçing. «Şartnomani oçiş» tugmasi biz yuborgan faylni körsatadi.',
        'Hammasi mos bölsa, «Şartnoma loyihasini kelişiş»ni bosing. Aks holda «Izoh bilan qaytariş» orqali nimani özgartiriş kerakligini yozing: yangi versiyani tayyorlaymiz.',
        'Kelişgaçdan keyin şartnomani imzolang va skanni yuklang: «Skanni yuklaş» (PDF yoki rasm). Skanni almaştiriş mumkin.',
        'Şartnomani tasdiqlaganimizda, menyuda hamkor bölimlari oçiladi.',
        'Kelişiş, qaytariş va skan yuklaşni harakatlarni tasdiqlaş huquqi bor vakil bajaradi.',
      ],
      en: [
        'Open “Company” and find the “Partner contract” card. “Open contract” shows the file we sent.',
        'If it suits you, press “Agree the draft contract”. If not, use “Return with a remark” and write what to change: we will prepare a new version.',
        'After you agree, sign the contract and upload the scan with “Upload scan” (PDF or image). You can replace the scan.',
        'Once we confirm the contract, the partner sections open in the menu.',
        'Agreeing, returning and uploading the scan is done by a representative who may confirm actions.',
      ],
    },
  },
  {
    id: 'quotes-accept',
    category: 'quotes',
    routePatterns: ['/', '/quotes'],
    title: {
      ru: 'Как принять или отклонить предложение',
      uz: 'Tijorat taklifini qanday qabul qiliş yoki rad etiş',
      en: 'How to accept or reject a quote',
    },
    summary: {
      ru: 'Порядок подтверждения предложения одноразовым кодом из письма (или из Telegram, если он подключён).',
      uz: 'Bir martalik kod orqali tijorat taklifini tasdiqlaş tartibi.',
      en: 'Procedure for confirming a quote via one-time code.',
    },
    content: {
      ru: [
        'Откройте нужное коммерческое предложение в разделе «Предложения».',
        'Если у вас есть право подтверждать, у предложения есть кнопки «Принять» и «Отклонить».',
        'При нажатии «Принять» вам будет направлен одноразовый 6-значный код (в Telegram или на почту). Введите его в поле подтверждения.',
        'После кода предложение принято — договор появится в «Договорах».',
      ],
      uz: [
        '«Takliflar» bölimida kerakli tijorat taklifini oçing.',
        'Agar sizda tasdiqlaş huquqi bölsa, takliflarda «Qabul qiliş» va «Rad etiş» tugmalari böladi.',
        '«Taklifni qabul qiliş» tugmasi bosilganda Telegram yoki poçtangizga 6 xonali tasdiqlaş kodi yuboriladi.',
        'Kod kiritilgaç taklif qabul qilinadi — şartnoma «Şartnomalar» bölimida paydo böladi.',
      ],
      en: [
        'Open the commercial quote in the "Quotes" section.',
        'If you have approval rights, the quote has "Accept" and "Reject" buttons.',
        'Clicking "Accept" will send a one-time 6-digit confirmation code via Telegram or email.',
        'Once you enter the code the quote is accepted — the contract appears under "Contracts".',
      ],
    },
  },
  {
    id: 'quotes-by-link',
    category: 'quotes',
    routePatterns: ['/quotes'],
    title: {
      ru: 'Предложение пришло ссылкой в письме: что с ней можно сделать?',
      uz: 'Taklif xatda havola bilan keldi: u bilan nima qiliş mumkin?',
      en: 'The quote came as a link in an e-mail: what can I do with it?',
    },
    summary: {
      ru: 'Ссылка открывает один документ; любое действие — после кода на вашу почту, и этот же код открывает ваш кабинет.',
      uz: 'Havola bitta hujjatni oçadi; har qanday amal — poçtangizga kelgan koddan keyin, şu kod Kabinetingizni ham oçadi.',
      en: 'The link opens one document; any action needs the code sent to your e-mail, and the same code opens your account.',
    },
    content: {
      ru: [
        'Ссылка из письма открывает только этот документ — предложение, договор, счёт или акт: ключевые факты и «Скачать PDF» (у предложения — ещё состав). Других документов и разделов по ней не видно.',
        'Что можно сделать: предложение — принять, вернуть с замечаниями или задать вопрос; договор — согласовать; акт — принять или вернуть с замечаниями. По счёту видны реквизиты и срок оплаты; если вы уже оплатили, платёж появится в счёте, когда мы его подтвердим, а платёжное поручение можно приложить в кабинете. Ссылка одного документа не открывает действий над другим.',
        'Чтобы выполнить действие, нажмите нужную кнопку — на адрес, куда пришло письмо, придёт код из шести цифр. Он действует 10 минут; новый код можно запросить через 45 секунд. Адрес в окне не меняется.',
        'Код — это и вход: после него открыт ваш кабинет с договором, счетами и актами, а начатое действие выполняется само. При первом входе нужно принять условия использования и политику обработки персональных данных.',
        'Если вы уже вошли в кабинет, код не нужен. Кнопки решения неактивны, если у вас нет права принимать решения, — обратитесь к администратору компании.',
        'Ссылку может отозвать отправитель, а срок её действия ограничен: тогда страница покажет только причину. Запросите новую у отправителя.',
      ],
      uz: [
        'Xatdagi havola faqat şu hujjatni oçadi — taklif, şartnoma, hisob yoki dalolatnoma: asosiy maʼlumotlar va «PDF yuklab oliş» (taklifda tarkibi ham). Boşqa hujjat va bölimlar körinmaydi.',
        'Nima qiliş mumkin: taklif — qabul qiliş, izoh bilan qaytariş yoki savol beriş; şartnoma — kelişiş; dalolatnoma — qabul qiliş yoki izoh bilan qaytariş. Hisobda rekvizitlar va tölov muddati körinadi; tölagan bölsangiz, tölov biz tasdiqlagaç hisobda paydo böladi, tölov topşiriqnomasini kabinetda ilova qilişingiz mumkin. Bir hujjat havolasi boşqa hujjat üstida amal qilişga yöl bermaydi.',
        'Amalni bajariş uçun kerakli tugmani bosing — xat kelgan manzilga oltita raqamli kod keladi. U 10 daqiqa amal qiladi; yangi kodni 45 soniyadan keyin söraş mumkin. Oynada manzil özgarmaydi.',
        'Kod — bu kiriş ham: undan keyin şartnoma, hisoblar va dalolatnomalar bilan Kabinetingiz oçiladi, boşlangan amal özi bajariladi. Birinçi kirişda foydalaniş şartlari va şaxsga doir maʼlumotlarga işlov beriş siyosatini qabul qilişingiz kerak.',
        'Kabinetga allaqaçon kirgan bölsangiz, kod kerak emas. Sizda qaror qabul qilişga huquq bölmasa, qaror tugmalari faol bölmaydi — kompaniya administratoriga murojaat qiling.',
        'Havolani yuboruvçi bekor qilişi mumkin, uning amal qiliş muddati ham çegaralangan: bunda sahifa faqat sababni körsatadi. Yuboruvçidan yangisini sörang.',
      ],
      en: [
        'The link in the e-mail opens only this document — a quote, contract, invoice or act: the key facts and «Download PDF» (a quote also shows its contents). No other documents or sections are visible through it.',
        'What you can do: quote — accept, return with remarks or ask a question; contract — agree it; act — accept it or return it with remarks. An invoice shows the payment details and due date; if you have already paid, the payment appears in the invoice once we confirm it, and you can attach the payment order in your account. The link of one document never allows actions on another.',
        'To take the action, press the button — a six-digit code goes to the address the e-mail came to. It is valid for 10 minutes; a new one can be requested after 45 seconds. The address in the window cannot be changed.',
        'The code is also your sign-in: after it your account opens with contracts, invoices and acts, and the action you started runs by itself. On the first sign-in you accept the terms of use and the personal data policy.',
        'If you are already signed in, no code is needed. The decision buttons are inactive if you have no right to decide — ask your company administrator.',
        'The sender can revoke the link and it has an expiry date: then the page shows only the reason. Ask the sender for a new one.',
      ],
    },
  },
  {
    id: 'contracts-eds',
    category: 'billing',
    routePatterns: ['/billing', '/contracts'],
    title: {
      ru: 'Как согласовать договор и принять акт',
      uz: 'Şartnomani qanday kelişiş va dalolatnomani qabul qiliş',
      en: 'How to agree a contract and accept an act',
    },
    summary: {
      ru: 'Договор согласуют в кабинете, затем выставляют на подписание.',
      uz: 'Şartnoma kabinetda kelişiladi, söngra imzolaşga qöyiladi.',
      en: 'You agree the contract in your account; then it is sent for signing.',
    },
    content: {
      ru: [
        'Откройте «Договоры»: у договора «Ждёт вашего согласования» нажмите «Принять редакцию».',
        'Согласование подтверждает текст договора. Подписание — отдельный шаг: мы выставим договор на подписание и сообщим, когда он подписан.',
        'Акт — в «Актах»: нажмите «Принять», если всё в порядке, или «Вернуть» и опишите причину.',
      ],
      uz: [
        '«Şartnomalar» bölimini oçing: «Kelişişingizni kutmoqda» holatidagi şartnomada «Tahrirni qabul qiliş» tugmasini bosing.',
        'Kelişiş şartnoma matnini tasdiqlaydi. Imzolaş — alohida qadam: biz şartnomani imzolaşga qöyamiz va imzolanganda xabar beramiz.',
        'Dalolatnoma «Dalolatnomalar» bölimida: hammasi joyida bölsa «Qabul qiliş», aks holda «Qaytariş» tugmasini bosing va sababini yozing.',
      ],
      en: [
        'Open “Contracts”: for a contract marked “Awaiting your agreement” press “Accept the edition”.',
        'Agreeing confirms the text of the contract. Signing is a separate step: we will send the contract for signing and tell you when it is signed.',
        'An act is under “Acts”: press “Accept” if everything is fine, or “Return” and describe the reason.',
      ],
    },
  },
  {
    id: 'invoices-payment',
    category: 'billing',
    routePatterns: ['/billing', '/invoices'],
    title: {
      ru: 'Оплата счетов и финансовые документы',
      uz: 'Hisoblarni töleş va moliyaviy hujjatlar',
      en: 'Invoice payments and billing documents',
    },
    summary: {
      ru: 'Где скачать счёт на оплату и как отметить оплату.',
      uz: 'Tölov hisobini qayerdan yuklab oliş va tölovni qanday belgilaş.',
      en: 'Where to download an invoice and how to report a payment.',
    },
    content: {
      ru: [
        'Счета — в разделе «Счета»: PDF с реквизитами скачивается кнопкой «Скачать». QR-код в PDF нужен для проверки подлинности счёта.',
        'Оплатили — нажмите «Я оплатил» и приложите платёжное поручение.',
        'Когда мы подтвердим поступление, счёт станет «Оплачен» и придёт уведомление.',
      ],
      uz: [
        'Hisoblar «Hisoblar» bölimida: rekvizitli PDF «Yuklab oliş» tugmasi bilan yuklanadi. PDFdagi QR-kod hisobning asl ekanini tekşiriş uçun.',
        'Töladingiz — «Töladim» tugmasini bosing va tölov topşiriqnomasini biriktiring.',
        'Tuşumni tasdiqlaganimizda hisob «Tölangan» bölib, bildirişnoma keladi.',
      ],
      en: [
        'Invoices are under “Invoices”: download the PDF with payment details with “Download”. The QR code in the PDF is for checking that the invoice is genuine.',
        'Once you have paid, press “I have paid” and attach the payment order.',
        'When we confirm the payment, the invoice becomes “Paid” and you get a notification.',
      ],
    },
  },
  {
    id: 'deliveries-tracking',
    category: 'deliveries',
    routePatterns: ['/deliveries'],
    title: {
      ru: 'Отслеживание поставок и отгрузок',
      uz: 'Yetkazib beriş va jönatmalarni kuzatiş',
      en: 'Shipment and delivery tracking',
    },
    summary: {
      ru: 'Контроль этапов комплектации, отправки и поступления на склад.',
      uz: 'Yetkazib beriş bosqiçlari va omborga kelib tuşiş nazorati.',
      en: 'Monitoring fulfillment, transit, and warehouse delivery.',
    },
    content: {
      ru: [
        'Раздел «Поставки» содержит подробную информацию обо всех отгрузках по вашим проектам.',
        'Для каждой поставки отображаются текущий статус, ориентировочная дата прибытия и список позиций.',
        'При изменении статуса поставки (отправлено, прибыло) вам поступит уведомление в выбранные каналы связи.',
      ],
      uz: [
        '«Yetkazib beriş» bölimida barça jönatmalar böyiça töliq maʼlumot mavjud.',
        'Har bir yetkazib beriş uçun joriy holat, yetib keliş sanasi va tovarlar röyxati körsatiladi.',
        'Holat özgarganda (jönatildi, yetib keldi) belgilangan aloqa kanallariga xabar yuboriladi.',
      ],
      en: [
        'The "Deliveries" section displays all shipments associated with your projects.',
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
      uz: 'Jamoani boşqariş va bank rekvizitlari xavfsizligi',
      en: 'Team management and bank requisites protection',
    },
    summary: {
      ru: 'Приглашение сотрудников, роли и ограничение изменения реквизитов.',
      uz: 'Xodimlarni taklif qiliş va rekvizitlar özgarişini çeklaş.',
      en: 'Inviting colleagues, roles, and requisites change restrictions.',
    },
    content: {
      ru: [
        'Администратор компании может приглашать коллег в разделе «Команда».',
        'Права: только просмотр, «Может подтверждать» и «Администратор компании».',
        'Важно: смену банковских реквизитов подаёт только администратор, а применяется она после подтверждения сотрудником; до этого действуют старые реквизиты. Все администраторы и основной контакт получают уведомление во всех каналах.',
        'Логотип компании на странице «Компания» видят все участники; администратор загружает его кнопкой «Загрузить логотип» (PNG, JPEG или WebP до 2 МБ, по центру обрезается до квадрата), заменяет или убирает. Пока логотипа нет, показаны буквы названия.',
      ],
      uz: [
        'Kompaniya administratori «Jamoa» bölimida xodimlarni taklif qilişi mumkin.',
        'Huquqlar: faqat köriş, «Tasdiqlaş mumkin» va «Kompaniya administratori».',
        'Muhim: bank rekvizitlarini özgartiriş sörovini faqat administrator yuboradi, özgariş xodim tasdiğidan keyin qöllanadi; şu vaqtgaça eski rekvizitlar amalda. Barça administratorlar va asosiy kontakt barça kanallarda bildirişnoma oladi.',
        'Kompaniya logotipini «Kompaniya» sahifasida barça iştirokçilar köradi; administrator uni «Logotip yuklaş» tugmasi bilan yuklaydi (PNG, JPEG yoki WebP, 2 MB gaça, markazdan kvadratga kesiladi), almaştiradi yoki olib taşlaydi. Logotip bölmaganda kompaniya nomining harflari körsatiladi.',
      ],
      en: [
        'Company administrators can invite colleagues in the "Team" section.',
        'Rights: view only, “Can approve” and “Company administrator”.',
        'Important: only an administrator can request a bank details change, and it applies only after a staff member confirms it; until then the old details remain in effect. All admins and the primary contact are notified on every channel.',
        'Everyone in the company sees the company logo on the "Company" page; an administrator uploads it with "Upload logo" (PNG, JPEG or WebP up to 2 MB, cropped to a centered square), replaces or removes it. Until there is a logo, the letters of the company name are shown.',
      ],
    },
  },
  {
    id: 'profile-notifications-channels',
    category: 'profile',
    routePatterns: ['/profile'],
    title: {
      ru: 'Каналы уведомлений и привязка Telegram',
      uz: 'Xabarnomalar kanallari va Telegramni ulaş',
      en: 'Notification channels and Telegram binding',
    },
    summary: {
      ru: 'Настройка уведомлений в Telegram, на e-mail и в кабинете.',
      uz: 'Telegram, E-mail va kabinetda bildirişnomalarni sozlaş.',
      en: 'Configuring Telegram, e-mail and in-account notifications.',
    },
    content: {
      ru: [
        'В разделе «Профиль» подключите наш Telegram-бот: уведомления будут приходить в него, а кабинет откроется прямо в боте.',
        'В таблице «Каналы уведомлений» вы можете настроить, какие категории событий (документы, финансы, поставки, сообщения) отправлять на почту или в Telegram.',
        'Оповещения безопасности (вход с нового устройства, изменение реквизитов) обязательны и доставляются во все доступные каналы.',
      ],
      uz: [
        '«Profil» bölimida bildirişnomalar botga kelişi va kabinet unda oçilişi uçun Telegram botni ulang.',
        '«Xabarnoma kanallari» jadvalida qaysi voqealar (hujjatlar, moliya, yetkazib beriş) qaysi kanalga borişini tanlang.',
        'Xavfsizlik ogohlantirişlari barça ulangan kanallarga majburiy yuboriladi.',
      ],
      en: [
        'In "Profile", connect our Telegram bot: notifications arrive in it and your account opens right in the bot.',
        'Use the Notification Channels table to select event groups (documents, money, deliveries, messages) for Email or Telegram.',
        'Security notices are always dispatched to all available channels.',
      ],
    },
  },
  {
    id: 'partner-products-guide',
    category: 'products',
    routePatterns: ['/my-products'],
    title: {
      ru: '«Мои товары»: прайс и цены',
      uz: '«Mening tovarlarim»: prays va narxlar',
      en: 'My Products: price list and prices',
    },
    summary: {
      ru: 'Загрузка прайса, проверка карточек и контроль цен.',
      uz: 'Prays yuklaş, kartoçkalarni tekşiriş va narxlarni nazorat qiliş.',
      en: 'Price-list upload, card review and price control.',
    },
    content: {
      ru: [
        'Загрузите прайс по шаблону — карточки появятся черновиками.',
        'Отправьте их на проверку: после неё опубликуем в каталоге.',
        'Документы к своей карточке (сертификат, паспорт) сначала проверяет сотрудник: пока документ «На проверке», клиенты его не видят. Удалить можно только присланный вами документ.',
      ],
      uz: [
        'Prays şablon böyiça yuklang — kartoçkalar qoralama bölib çiqadi.',
        'Ularni tekşiruvga yuboring: tekşiruvdan keyin katalogda eʼlon qilamiz.',
        'Kartoçkaga yuklangan hujjatlarni (sertifikat, pasport) avval xodim tekşiradi: «Tekşiruvda» holatida mijozlar ularni körmaydi. Faqat özingiz yuborgan hujjatni öçiriş mumkin.',
      ],
      en: [
        'Upload your price list using the template — the cards appear as drafts.',
        'Send them for review: after it we publish them in the catalog.',
        'Documents you add to your card (certificates, passports) are reviewed by staff first: while a document is "Under review", clients cannot see it. You can delete only documents you sent yourself.',
      ],
    },
  },
  {
    id: 'messages-support',
    category: 'messages',
    routePatterns: ['/messages'],
    title: {
      ru: 'Сообщения менеджеру',
      uz: 'Menejerga xabarlar',
      en: 'Messages to your manager',
    },
    summary: {
      ru: 'Вопросы по заявкам, поставкам и документам.',
      uz: 'Arizalar, yetkazib beriş va hujjatlar böyiça savollar.',
      en: 'Questions about requests, deliveries and documents.',
    },
    content: {
      ru: [
        'В разделе «Сообщения» можно написать менеджеру, который ведёт вашу компанию.',
        'Спрашивайте о заявках, поставках и документах. Файлы прикладывайте к заявке.',
        'О новых ответах придёт уведомление в каналы, которые вы выбрали в «Профиле».',
      ],
      uz: [
        '«Xabarlar» bölimida kompaniyangizni yurituvçi menejerga yozişingiz mumkin.',
        'Arizalar, yetkazib beriş va hujjatlar haqida sörang. Fayllarni arizaga biriktiring.',
        'Yangi javoblar haqida «Profil»da tanlagan kanallaringizga bildirişnoma keladi.',
      ],
      en: [
        'In “Messages” you can write to the manager who looks after your company.',
        'Ask about requests, deliveries and documents. Attach files to a request.',
        'New replies are announced in the channels you chose in “Profile”.',
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

/**
 * Uzbek search key: the new alphabet and the old one are one spelling (owner 2026-11-17),
 * so ö = oʻ / o', ğ = gʻ / g', ş = sh, ç = ch — a query in either finds the other.
 */
export function foldUz(text: string): string {
  return text
    .toLowerCase()
    .replace(/([og])['\u02bb\u02bc\u2018\u2019`]/g, (_m, letter: string) => (letter === 'o' ? 'ö' : 'ğ'))
    .replace(/sh/g, 'ş')
    .replace(/ch/g, 'ç');
}

export function searchHelpArticles(query: string, lang: 'ru' | 'uz' | 'en'): HelpArticle[] {
  const q = foldUz(query.trim());
  if (!q) return HELP_ARTICLES;

  return HELP_ARTICLES.filter((article) => {
    const title = foldUz(article.title[lang]);
    const summary = foldUz(article.summary[lang]);
    const content = foldUz(article.content[lang].join(' '));
    return title.includes(q) || summary.includes(q) || content.includes(q);
  });
}
