// Sample product data from the imported Excel specification (УЭЛ для НХ 2026)
// Domain types: RAILWAY_MACHINERY, GENERAL_GOODS, SERVICES

export interface Product {
  id: string;
  name: string;
  article: string;
  gost: string;
  uom: string;
  quantity: number;
  domain: 'RAILWAY_MACHINERY' | 'GENERAL_GOODS' | 'SERVICES';
  category: string;
  status: 'in_stock' | 'to_order' | 'sourcing' | 'inactive';
  manufacturer: string;
  addedDate: string;
  /** Company ID that owns/created this product (manufacturer) */
  ownerCompanyId: string;
  /** Whether this product is visible to partnered sellers */
  partnerVisible: boolean;
  /** Seller company IDs that have partnership access */
  approvedSellers?: string[];
  /** Base price visible to partners (FCA) */
  basePriceFCA?: number;
  // Extended fields for product detail card (FEROX-style)
  description?: string;
  materialId?: string;
  iso?: string;
  packageQuantity?: number;
  images?: string[];
  similarProducts?: string[];
  matchingTools?: number;
  specifications?: Record<string, string>;
  prevQuantity?: number;
}

export const products: Product[] = [
  {
    id: 'P001', name: 'Баббит Б-83', article: 'MAT-001', gost: 'ГОСТ 1320-74', uom: 'тн', quantity: 20,
    domain: 'GENERAL_GOODS', category: 'Материалы', status: 'in_stock', manufacturer: 'ОАО ММЗ', addedDate: '15.01.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 9650,
    description: 'Баббит марки Б-83 — высокооловянный антифрикционный сплав для заливки подшипников скольжения тяговых двигателей и вспомогательных машин подвижного состава.',
    materialId: 'MAT-001-B83', iso: '4381', packageQuantity: 25, prevQuantity: 18,
    specifications: { 'Марка': 'Б-83', 'Олово (Sn)': '83%', 'Сурьма (Sb)': '11%', 'Медь (Cu)': '6%', 'Температура плавления': '240°C', 'Твёрдость HB': '27–30' },
    matchingTools: 4,
  },
  {
    id: 'P002', name: 'Баббит БК-2', article: 'MAT-002', gost: 'ГОСТ 1209-90', uom: 'тн', quantity: 30,
    domain: 'GENERAL_GOODS', category: 'Материалы', status: 'in_stock', manufacturer: 'ОАО ММЗ', addedDate: '15.01.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 9650,
    description: 'Баббит кальциевый БК-2 для подшипников скольжения тепловозов, используется в железнодорожной отрасли.', materialId: 'MAT-002-BK2', iso: '4382', packageQuantity: 25, prevQuantity: 28,
    specifications: { 'Марка': 'БК-2', 'Свинец (Pb)': '96.6%', 'Кальций (Ca)': '0.7%', 'Натрий (Na)': '0.9%' },
  },
  {
    id: 'P003', name: 'Олово марка О1 пч', article: 'MAT-003', gost: 'ГОСТ 860-75', uom: 'тн', quantity: 20,
    domain: 'GENERAL_GOODS', category: 'Материалы', status: 'to_order', manufacturer: 'АО Новосибирский ОЗ', addedDate: '20.01.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 4060,
    description: 'Олово высокой чистоты марки О1пч для пайки электрических соединений и производства баббитов.',
    materialId: 'MAT-003-O1', packageQuantity: 10, prevQuantity: 22,
    specifications: { 'Марка': 'О1 пч', 'Олово (Sn)': '99.915%', 'Примеси': '<0.085%' },
  },
  {
    id: 'P004', name: 'Бронза оловянная Бр04Ц4С17', article: 'MAT-004', gost: 'Бр04Ц4С17', uom: 'тн', quantity: 40,
    domain: 'GENERAL_GOODS', category: 'Материалы', status: 'in_stock', manufacturer: 'ОАО Кировский завод', addedDate: '22.01.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 2110,
    description: 'Оловянная бронза для втулок, вкладышей и подшипников подвижного состава. Высокая износостойкость.',
    materialId: 'MAT-004-BR', packageQuantity: 20, prevQuantity: 35,
    specifications: { 'Олово (Sn)': '4%', 'Цинк (Zn)': '4%', 'Свинец (Pb)': '17%' },
  },
  {
    id: 'P005', name: 'Провод БПВЛ 1,5 мм²', article: 'ELC-001', gost: 'ТУ16.505.911-76', uom: 'км', quantity: 300,
    domain: 'RAILWAY_MACHINERY', category: 'Электрооборудование', status: 'in_stock', manufacturer: 'АО МТЗ Трансмаш', addedDate: '01.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 7910,
    description: 'Провод бортовой полимерный лакированный для монтажа электрических цепей локомотивов, вагонов и электропоездов.',
    materialId: 'ELC-001-BPVL', packageQuantity: 500, prevQuantity: 280,
    specifications: { 'Сечение': '1.5 мм²', 'Тип изоляции': 'Полимерная лакированная', 'Рабочая температура': '-50°C … +105°C', 'Напряжение': 'до 1000В' },
    matchingTools: 8,
  },
  {
    id: 'P006', name: 'Провод БПВЛ 2,5 мм²', article: 'ELC-002', gost: 'ТУ16.505.911-76', uom: 'км', quantity: 300,
    domain: 'RAILWAY_MACHINERY', category: 'Электрооборудование', status: 'to_order', manufacturer: 'АО МТЗ Трансмаш', addedDate: '01.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 7910,
    description: 'Провод бортовой полимерный лакированный сечением 2,5 мм² для силовых цепей подвижного состава.',
    materialId: 'ELC-002-BPVL', packageQuantity: 500, prevQuantity: 310,
    specifications: { 'Сечение': '2.5 мм²', 'Тип изоляции': 'Полимерная лакированная', 'Рабочая температура': '-50°C … +105°C', 'Напряжение': 'до 1000В' },
    matchingTools: 8,
  },
  {
    id: 'P007', name: 'Круг ø120мм ст. 12ХН3А', article: 'MET-001', gost: 'ст. 12ХН3А', uom: 'тн', quantity: 30,
    domain: 'GENERAL_GOODS', category: 'Металлопрокат', status: 'in_stock', manufacturer: 'ПАО Северсталь', addedDate: '05.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 2680,
    description: 'Круг горячекатаный диаметром 120мм из легированной стали 12ХН3А для изготовления шестерён и валов локомотивов.',
    materialId: 'MET-001-12XN3A', packageQuantity: 50, prevQuantity: 28,
    specifications: { 'Диаметр': '120 мм', 'Сталь': '12ХН3А', 'Поставка': 'Прутки', 'Длина': '2–6 м' },
    matchingTools: 12,
  },
  {
    id: 'P008', name: 'Круг ø140мм ст. 12ХН3А', article: 'MET-002', gost: 'ст. 12ХН3А', uom: 'тн', quantity: 25,
    domain: 'GENERAL_GOODS', category: 'Металлопрокат', status: 'sourcing', manufacturer: 'ПАО Северсталь', addedDate: '05.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 2680,
    description: 'Круг горячекатаный диаметром 140мм из стали 12ХН3А.', materialId: 'MET-002-12XN3A', packageQuantity: 50, prevQuantity: 30,
    specifications: { 'Диаметр': '140 мм', 'Сталь': '12ХН3А' },
  },
  {
    id: 'P009', name: 'Круг ø160мм ст. 12ХН3А', article: 'MET-003', gost: 'ст. 12ХН3А', uom: 'тн', quantity: 40,
    domain: 'GENERAL_GOODS', category: 'Металлопрокат', status: 'in_stock', manufacturer: 'ПАО Северсталь', addedDate: '10.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 2680,
    description: 'Круг горячекатаный ø160мм, сталь 12ХН3А.', materialId: 'MET-003-12XN3A', packageQuantity: 50, prevQuantity: 38,
    specifications: { 'Диаметр': '160 мм', 'Сталь': '12ХН3А' },
  },
  {
    id: 'P010', name: 'Круг ø200мм ст. 12ХН3А', article: 'MET-004', gost: 'ст. 12ХН3А', uom: 'тн', quantity: 20,
    domain: 'GENERAL_GOODS', category: 'Металлопрокат', status: 'to_order', manufacturer: 'ПАО Северсталь', addedDate: '10.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 2680,
    description: 'Круг горячекатаный ø200мм, сталь 12ХН3А.', materialId: 'MET-004-12XN3A', packageQuantity: 50, prevQuantity: 22,
    specifications: { 'Диаметр': '200 мм', 'Сталь': '12ХН3А' },
  },
  {
    id: 'P011', name: 'Лента 0,5мм ст. 30ХГСА', article: 'MET-005', gost: '30ХГСА', uom: 'тн', quantity: 15,
    domain: 'GENERAL_GOODS', category: 'Металлопрокат', status: 'in_stock', manufacturer: 'ПАО НЛМК', addedDate: '12.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 7240,
    description: 'Лента стальная толщиной 0,5мм из хромомарганцевокремнистой стали 30ХГСА.', prevQuantity: 12,
    specifications: { 'Толщина': '0.5 мм', 'Сталь': '30ХГСА' },
  },
  {
    id: 'P012', name: 'Чугун ПЛ-2', article: 'MET-006', gost: '—', uom: 'тн', quantity: 10,
    domain: 'GENERAL_GOODS', category: 'Металлопрокат', status: 'inactive', manufacturer: 'ОАО ЧМЗ', addedDate: '15.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 1710,
    description: 'Чугун литейный марки ПЛ-2.', prevQuantity: 10,
  },
  {
    id: 'P013', name: 'Эмаль ЭЛКОМ ЭИ-401', article: 'CHM-001', gost: '—', uom: 'тн', quantity: 5,
    domain: 'GENERAL_GOODS', category: 'Химия и ЛКМ', status: 'in_stock', manufacturer: 'ООО ЭЛКОМ', addedDate: '18.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 5660,
    description: 'Электроизоляционная эмаль ЭИ-401 для пропитки обмоток тяговых электродвигателей.', prevQuantity: 4,
    specifications: { 'Тип': 'Электроизоляционная', 'Класс нагревостойкости': 'F (155°C)' },
  },
  {
    id: 'P014', name: 'Лента элмикатерм 0,08х20мм', article: 'INS-001', gost: '—', uom: 'тн', quantity: 8,
    domain: 'RAILWAY_MACHINERY', category: 'Изоляция', status: 'sourcing', manufacturer: 'ООО НПО САУТ', addedDate: '20.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 9630,
    description: 'Слюдяная лента элмикатерм для высокотемпературной изоляции обмоток тяговых двигателей.', prevQuantity: 10,
    specifications: { 'Размер': '0.08×20 мм', 'Материал': 'Слюда + полиимид', 'Класс': 'H (180°C)' },
  },
  {
    id: 'P015', name: 'Стеклотекстолит СТЭФ-1 5мм', article: 'INS-002', gost: '—', uom: 'тн', quantity: 12,
    domain: 'RAILWAY_MACHINERY', category: 'Изоляция', status: 'to_order', manufacturer: 'ОАО ЭЛИЗ', addedDate: '25.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 5660,
    description: 'Стеклотекстолит электротехнический фольгированный, толщина 5мм.', prevQuantity: 14,
    specifications: { 'Толщина': '5 мм', 'Материал': 'Стекловолокно + эпоксидная смола' },
  },
  {
    id: 'P016', name: 'Доставка ЖД транспортом (Россия-Узбекистан)', article: 'SVC-001', gost: '—', uom: 'рейс', quantity: 24,
    domain: 'SERVICES', category: 'Логистика', status: 'in_stock', manufacturer: 'ООО РТ Логистик', addedDate: '01.01.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 8270,
    description: 'Услуга доставки грузов железнодорожным транспортом по маршруту Россия — Узбекистан.', prevQuantity: 20,
    specifications: { 'Маршрут': 'РФ → УЗ', 'Тип вагона': 'Крытый / Полувагон', 'Срок доставки': '15–25 дней' },
  },
  {
    id: 'P017', name: 'Таможенное оформление (импорт)', article: 'SVC-002', gost: '—', uom: 'партия', quantity: 48,
    domain: 'SERVICES', category: 'Таможня', status: 'in_stock', manufacturer: 'ООО РТ Логистик', addedDate: '01.01.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 8270,
    description: 'Комплексное таможенное оформление импортных грузов при ввозе на территорию Узбекистана.', prevQuantity: 42,
    specifications: { 'Тип': 'Импорт', 'Документы': 'ГТД, инвойс, упаковочный лист', 'Срок': '2–5 рабочих дней' },
  },
  {
    id: 'P018', name: 'Круг ø160мм ст. 38ХС', article: 'MET-007', gost: 'ст. 38ХС', uom: 'тн', quantity: 35,
    domain: 'GENERAL_GOODS', category: 'Металлопрокат', status: 'in_stock', manufacturer: 'ПАО Северсталь', addedDate: '28.02.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 2680,
    description: 'Круг горячекатаный ø160мм из стали 38ХС.', prevQuantity: 32,
    specifications: { 'Диаметр': '160 мм', 'Сталь': '38ХС' },
  },
  {
    id: 'P019', name: 'Круг ø160мм ст. У8', article: 'MET-008', gost: 'ст. У8', uom: 'тн', quantity: 18,
    domain: 'GENERAL_GOODS', category: 'Металлопрокат', status: 'to_order', manufacturer: 'ПАО НЛМК', addedDate: '01.03.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 7240,
    description: 'Круг из инструментальной углеродистой стали У8.', prevQuantity: 20,
    specifications: { 'Диаметр': '160 мм', 'Сталь': 'У8', 'Твёрдость': 'HRC 56–64' },
  },
  {
    id: 'P020', name: 'Полиамидная лента ПМ(л) 0,045х20мм', article: 'INS-003', gost: '—', uom: 'тн', quantity: 6,
    domain: 'RAILWAY_MACHINERY', category: 'Изоляция', status: 'in_stock', manufacturer: 'ООО НПО САУТ', addedDate: '05.03.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 9630,
    description: 'Полиамидная плёночная лента лакированная для межвитковой изоляции обмоток электрических машин.', prevQuantity: 5,
    specifications: { 'Размер': '0.045×20 мм', 'Материал': 'Полиамид (капрон)', 'Класс': 'B (130°C)' },
  },

  // NEW PRODUCTS: RAILWAY_MACHINERY (15 items)
  {
    id: 'P021', name: 'Тележки грузовые модель 18-100', article: 'RLM-001', gost: 'ГОСТ 9245-82', uom: 'шт', quantity: 8,
    domain: 'RAILWAY_MACHINERY', category: 'Ходовые части', status: 'in_stock', manufacturer: 'АО САУT', addedDate: '08.03.2026',
    ownerCompanyId: 'C_SAUT', partnerVisible: true, approvedSellers: ['C_SELF', 'C_SAUT'], basePriceFCA: 18500,
    description: 'Четырёхосная грузовая тележка модель 18-100 с грузоподъёмностью 100 тонн для универсального подвижного состава.',
    materialId: 'RLM-001-T18', packageQuantity: 1, prevQuantity: 6,
    specifications: { 'Грузоподъёмность': '100 т', 'Осей': '4', 'Колёсные пары': '4', 'Рессорное подвешивание': 'Листовое + амортизаторы', 'Вес': '4.2 т' },
    matchingTools: 3,
  },
  {
    id: 'P022', name: 'Колёсные пары РУ1Ш-957-Г', article: 'RLM-002', gost: 'ГОСТ 10791-2016', uom: 'шт', quantity: 24,
    domain: 'RAILWAY_MACHINERY', category: 'Колёсные пары', status: 'in_stock', manufacturer: 'АО SAUT', addedDate: '10.03.2026',
    ownerCompanyId: 'C_SAUT', partnerVisible: true, approvedSellers: ['C_SELF', 'C_SAUT'], basePriceFCA: 8400,
    description: 'Колёсная пара РУ1Ш-957-Г на роликоподшипниках для грузовых вагонов, износостойкие колёса из инструментальной стали.',
    materialId: 'RLM-002-CP957', packageQuantity: 2, prevQuantity: 20,
    specifications: { 'Диаметр колеса': '957 мм', 'Тип подшипника': 'Роликовый', 'Осевая нагрузка': 'до 130 кН', 'Класс точности': 'Т2' },
    matchingTools: 7,
  },
  {
    id: 'P023', name: 'Тяговый двигатель ЭД-118А', article: 'RLM-003', gost: 'ТУ 32.144-54-2003', uom: 'шт', quantity: 5,
    domain: 'RAILWAY_MACHINERY', category: 'Электрооборудование', status: 'to_order', manufacturer: 'АО РАТЭп', addedDate: '12.03.2026',
    ownerCompanyId: 'C_RATEP', partnerVisible: true, approvedSellers: ['C_SELF', 'C_RATEP'], basePriceFCA: 42000,
    description: 'Тяговый электродвигатель ЭД-118А мощностью 118 кВт для локомотивов постоянного и переменного тока, реверсивный.',
    materialId: 'RLM-003-ED118', packageQuantity: 1, prevQuantity: 4,
    specifications: { 'Мощность': '118 кВт', 'Напряжение': '1500В постоянного тока', 'Частота вращения': '2000 об/мин', 'Охлаждение': 'Форсированное', 'Класс изоляции': 'F' },
    matchingTools: 5,
  },
  {
    id: 'P024', name: 'Автосцепка СА-3', article: 'RLM-004', gost: 'ГОСТ 25999-2016', uom: 'шт', quantity: 48,
    domain: 'RAILWAY_MACHINERY', category: 'Сцепные устройства', status: 'in_stock', manufacturer: 'АО SAUT', addedDate: '14.03.2026',
    ownerCompanyId: 'C_SAUT', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 3200,
    description: 'Автоматическая сцепка СА-3 (СА-3М) с предохранительными и ударными приспособлениями для вагонов и локомотивов.',
    materialId: 'RLM-004-SA3', packageQuantity: 4, prevQuantity: 44,
    specifications: { 'Рабочая нагрузка': '170 кН', 'Материал': 'Сталь 35Л', 'Буферное устройство': 'Фрикционно-упругое', 'Высота оси': '900 мм' },
    matchingTools: 6,
  },
  {
    id: 'P025', name: 'Тормозной цилиндр ТЦ-320', article: 'RLM-005', gost: 'ТУ 32.144.80-99', uom: 'шт', quantity: 32,
    domain: 'RAILWAY_MACHINERY', category: 'Тормозное оборудование', status: 'in_stock', manufacturer: 'АО РАТЭп', addedDate: '16.03.2026',
    ownerCompanyId: 'C_RATEP', partnerVisible: true, approvedSellers: ['C_SELF', 'C_RATEP'], basePriceFCA: 5600,
    description: 'Тормозной цилиндр ТЦ-320 объёмом 320 см³ для пневматической тормозной системы подвижного состава.',
    materialId: 'RLM-005-TC320', packageQuantity: 2, prevQuantity: 30,
    specifications: { 'Объём': '320 см³', 'Диаметр поршня': '160 мм', 'Ход поршня': '180 мм', 'Давление': 'до 8 атм', 'Материал': 'Чугун, Сталь' },
    matchingTools: 4,
  },
  {
    id: 'P026', name: 'Компрессор ВУ-3.5/10', article: 'RLM-006', gost: 'ТУ 32.144-39-2001', uom: 'шт', quantity: 6,
    domain: 'RAILWAY_MACHINERY', category: 'Пневматика', status: 'to_order', manufacturer: 'АО РАТЭп', addedDate: '18.03.2026',
    ownerCompanyId: 'C_RATEP', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 24500,
    description: 'Воздушный компрессор ВУ-3.5/10 для наддува тепловозов, производительность 3.5 м³/мин при 10 атм.',
    materialId: 'RLM-006-VU35', packageQuantity: 1, prevQuantity: 5,
    specifications: { 'Производительность': '3.5 м³/мин', 'Давление': '10 атм', 'Мощность': '75 кВт', 'Охлаждение': 'Водяное', 'Вес': '650 кг' },
    matchingTools: 3,
  },
  {
    id: 'P027', name: 'Букса ЦНИИ-Х3-0', article: 'RLM-007', gost: 'ГОСТ 18407-2016', uom: 'шт', quantity: 56,
    domain: 'RAILWAY_MACHINERY', category: 'Ходовые части', status: 'in_stock', manufacturer: 'АО SAUT', addedDate: '20.03.2026',
    ownerCompanyId: 'C_SAUT', partnerVisible: true, approvedSellers: ['C_SELF', 'C_OTHER'], basePriceFCA: 2800,
    description: 'Букса шарикоподшипниковая ЦНИИ-Х3-0 с встроенным амортизатором для пассажирского подвижного состава.',
    materialId: 'RLM-007-BKSA', packageQuantity: 4, prevQuantity: 52,
    specifications: { 'Диаметр оси': '32 мм', 'Тип подшипника': 'Шарикоподшипник', 'Амортизатор': 'Встроенный резиновый', 'Смазка': 'ЦИАТИМ-201' },
    matchingTools: 5,
  },
  {
    id: 'P028', name: 'Редуктор ЗУ-45', article: 'RLM-008', gost: 'ТУ 32.144-19-98', uom: 'шт', quantity: 4,
    domain: 'RAILWAY_MACHINERY', category: 'Трансмиссия', status: 'sourcing', manufacturer: 'АО SAUT', addedDate: '22.03.2026',
    ownerCompanyId: 'C_SAUT', partnerVisible: false, approvedSellers: ['C_SELF'], basePriceFCA: 16800,
    description: 'Редуктор с косозубыми колёсами ЗУ-45 для привода вспомогательных агрегатов тепловоза Зл45 (эксклюзив).',
    materialId: 'RLM-008-RED45', packageQuantity: 1, prevQuantity: 3,
    specifications: { 'Передаточное число': '2.48', 'Входящая мощность': '70 кВт', 'Выходной крутящий момент': '8500 Нм', 'Входная частота': '3000 об/мин' },
    matchingTools: 2,
  },
  {
    id: 'P029', name: 'Подшипник буксовый 232726', article: 'RLM-009', gost: 'ГОСТ 8338-2016', uom: 'шт', quantity: 120,
    domain: 'RAILWAY_MACHINERY', category: 'Подшипники', status: 'in_stock', manufacturer: 'АО SAUT', addedDate: '24.03.2026',
    ownerCompanyId: 'C_SAUT', partnerVisible: true, approvedSellers: ['C_SELF', 'C_SAUT', 'C_RATEP'], basePriceFCA: 1200,
    description: 'Шарикоподшипник буксовый 232726 с поддерживающим кольцом для оси подвижного состава, закаленный.',
    materialId: 'RLM-009-BK232', packageQuantity: 10, prevQuantity: 110,
    specifications: { 'Динамическая нагрузка': '370 кН', 'Статическая нагрузка': '370 кН', 'Частота вращения': '3500 об/мин', 'Зазор': '0.003–0.008 мм' },
    matchingTools: 8,
  },
  {
    id: 'P030', name: 'Рессора листовая Р75', article: 'RLM-010', gost: 'ГОСТ 3577-2016', uom: 'шт', quantity: 40,
    domain: 'RAILWAY_MACHINERY', category: 'Подвеска', status: 'in_stock', manufacturer: 'ООО ОПЗ', addedDate: '26.03.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 3400,
    description: 'Листовая рессора Р75 из хромокремнистой стали для грузовых вагонов, жёсткость 7.5 кН/мм.',
    materialId: 'RLM-010-RES75', packageQuantity: 2, prevQuantity: 38,
    specifications: { 'Жёсткость': '7.5 кН/мм', 'Рабочая нагрузка': '100 кН', 'Количество листьев': '6', 'Сталь': '50ХГФА' },
    matchingTools: 4,
  },
  {
    id: 'P031', name: 'Токоприёмник Т-5М1', article: 'RLM-011', gost: 'ГОСТ 2700-2015', uom: 'шт', quantity: 12,
    domain: 'RAILWAY_MACHINERY', category: 'Электроснабжение', status: 'in_stock', manufacturer: 'АО РАТЭп', addedDate: '28.03.2026',
    ownerCompanyId: 'C_RATEP', partnerVisible: true, approvedSellers: ['C_SELF', 'C_RATEP'], basePriceFCA: 8900,
    description: 'Жёсткий токоприёмник Т-5М1 для электровозов переменного тока 25 кВ, 50 Гц с панелью управления.',
    materialId: 'RLM-011-TP5M1', packageQuantity: 1, prevQuantity: 10,
    specifications: { 'Номинальное напряжение': '25 кВ', 'Частота': '50 Гц', 'Ток': 'до 500 А', 'Высота подъёма': '4.6–5.6 м', 'Материал контакта': 'Медь + углерод' },
    matchingTools: 3,
  },
  {
    id: 'P032', name: 'Генератор ГП-321', article: 'RLM-012', gost: 'ТУ 32.144-61-2002', uom: 'шт', quantity: 3,
    domain: 'RAILWAY_MACHINERY', category: 'Электрооборудование', status: 'to_order', manufacturer: 'АО РАТЭп', addedDate: '01.04.2026',
    ownerCompanyId: 'C_RATEP', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 28000,
    description: 'Генератор ГП-321 для подзарядки аккумуляторной батареи локомотива и питания вспомогательных цепей, мощность 32 кВт.',
    materialId: 'RLM-012-GP321', packageQuantity: 1, prevQuantity: 2,
    specifications: { 'Мощность': '32 кВт', 'Напряжение': '28В постоянного тока', 'Регулятор': 'Встроенный', 'Класс изоляции': 'B' },
    matchingTools: 2,
  },
  {
    id: 'P033', name: 'Пантограф ТАсС-10-01', article: 'RLM-013', gost: 'ТУ 32.144-67-2000', uom: 'шт', quantity: 8,
    domain: 'RAILWAY_MACHINERY', category: 'Электроснабжение', status: 'in_stock', manufacturer: 'АО РАТЭп', addedDate: '03.04.2026',
    ownerCompanyId: 'C_RATEP', partnerVisible: true, approvedSellers: ['C_SELF', 'C_RATEP'], basePriceFCA: 6700,
    description: 'Пантограф ТАсС-10-01 для электровозов и электропоездов переменного тока 25 кВ с системой стабилизации.',
    materialId: 'RLM-013-PANT10', packageQuantity: 1, prevQuantity: 7,
    specifications: { 'Номинальное напряжение': '25 кВ', 'Механизм подъёма': 'Пневматический', 'Ток контакта': 'до 400 А', 'Вес': '45 кг' },
    matchingTools: 3,
  },
  {
    id: 'P034', name: 'Кран машиниста 394', article: 'RLM-014', gost: 'ГОСТ 6035-2016', uom: 'шт', quantity: 28,
    domain: 'RAILWAY_MACHINERY', category: 'Управление', status: 'in_stock', manufacturer: 'АО SAUT', addedDate: '05.04.2026',
    ownerCompanyId: 'C_SAUT', partnerVisible: true, approvedSellers: ['C_SELF', 'C_SAUT'], basePriceFCA: 4100,
    description: 'Машинист кран 394 основной управления тормозной системой для пассажирских и грузовых локомотивов.',
    materialId: 'RLM-014-KR394', packageQuantity: 2, prevQuantity: 26,
    specifications: { 'Тип': 'Прямодействующий кран', 'Ток утечки': 'не более 30 мА', 'Рабочая температура': '-40…+50°C', 'Давление воздуха': '6–8 атм' },
    matchingTools: 5,
  },
  {
    id: 'P035', name: 'Блок автоматики АЛСН', article: 'RLM-015', gost: 'ТУ 32.144-51-2001', uom: 'шт', quantity: 6,
    domain: 'RAILWAY_MACHINERY', category: 'Автоматика', status: 'sourcing', manufacturer: 'АО SAUT', addedDate: '07.04.2026',
    ownerCompanyId: 'C_SAUT', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 11200,
    description: 'Блок автоматики АЛСН (автоматическая локомотивная сигнализация непрерывного действия) для управления электровоза.',
    materialId: 'RLM-015-ALS', packageQuantity: 1, prevQuantity: 5,
    specifications: { 'Тип сигнализации': 'АЛСН', 'Напряжение питания': '28В постоянного тока', 'Защита': 'IP54', 'Климатическое исполнение': 'УХЛ4' },
    matchingTools: 3,
  },

  // NEW PRODUCTS: GENERAL_GOODS (10 items)
  {
    id: 'P036', name: 'Трансформатор ТСЗМ-630', article: 'GEN-001', gost: 'ГОСТ 1570-96', uom: 'шт', quantity: 4,
    domain: 'GENERAL_GOODS', category: 'Электрооборудование', status: 'to_order', manufacturer: 'ОАО УЗЭТП', addedDate: '09.04.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF', 'C_OTHER'], basePriceFCA: 18500,
    description: 'Трансформатор сухой трёхфазный ТСЗМ-630/27 мощностью 630 кВА для питания тяговых подстанций.',
    materialId: 'GEN-001-TSZM630', packageQuantity: 1, prevQuantity: 3,
    specifications: { 'Мощность': '630 кВА', 'Напряжение': '110/27 кВ', 'Частота': '50 Гц', 'Охлаждение': 'Сухое', 'Потери холостого хода': '1.8 кВт' },
    matchingTools: 2,
  },
  {
    id: 'P037', name: 'Кабель КГН 3x16+1x6', article: 'GEN-002', gost: 'ГОСТ 1050-2018', uom: 'км', quantity: 150,
    domain: 'GENERAL_GOODS', category: 'Кабель и провод', status: 'in_stock', manufacturer: 'АО Нур-Кабель', addedDate: '11.04.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 4200,
    description: 'Кабель КГН (кабель гибкий нефритовый) с медной жилой сечением 3×16+1×6 мм² для полевых работ и переносных установок.',
    materialId: 'GEN-002-KGN316', packageQuantity: 100, prevQuantity: 140,
    specifications: { 'Жилы': '3×16 + 1×6 мм²', 'Напряжение': '660В', 'Материал жилы': 'Медь', 'Изоляция': 'Резина' },
    matchingTools: 4,
  },
  {
    id: 'P038', name: 'Смазка ЦИАТИМ-201', article: 'GEN-003', gost: 'ГОСТ 8581-2018', uom: 'тн', quantity: 22,
    domain: 'GENERAL_GOODS', category: 'Масла и смазки', status: 'in_stock', manufacturer: 'ООО НГЦ', addedDate: '13.04.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF', 'C_SAUT'], basePriceFCA: 2100,
    description: 'Смазка пластичная ЦИАТИМ-201 универсального применения для буксовых подшипников, цепей и механизмов подвижного состава.',
    materialId: 'GEN-003-TSIATIM201', packageQuantity: 20, prevQuantity: 20,
    specifications: { 'Тип': 'Литиевая пластичная', 'Температура каплепадения': '160°C', 'Предел прочности на сдвиг': '65–100 Па', 'Рабочая температура': '-30…+60°C' },
    matchingTools: 6,
  },
  {
    id: 'P039', name: 'Шланг тормозной Р17Б', article: 'GEN-004', gost: 'ГОСТ 5781-82', uom: 'км', quantity: 35,
    domain: 'GENERAL_GOODS', category: 'Пневматика', status: 'in_stock', manufacturer: 'ООО РТ Шланг', addedDate: '15.04.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 980,
    description: 'Шланг резиновый Р17Б для тормозных систем подвижного состава, рабочее давление 10 атм.',
    materialId: 'GEN-004-SHL17B', packageQuantity: 50, prevQuantity: 33,
    specifications: { 'Диаметр': '17 мм', 'Давление': '10 атм', 'Материал': 'Синтетический каучук', 'Длина катушки': '500 м' },
    matchingTools: 3,
  },
  {
    id: 'P040', name: 'Болты высокопрочные М24', article: 'GEN-005', gost: 'ГОСТ 10602-2014', uom: 'тн', quantity: 15,
    domain: 'GENERAL_GOODS', category: 'Крепёж', status: 'in_stock', manufacturer: 'АО Крепёж Вольга', addedDate: '17.04.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF', 'C_OTHER'], basePriceFCA: 3600,
    description: 'Болты высокопрочные оцинкованные М24×60 класса прочности 8.8 для критических соединений подвижного состава.',
    materialId: 'GEN-005-BLT24', packageQuantity: 100, prevQuantity: 14,
    specifications: { 'Диаметр': 'М24', 'Класс прочности': '8.8', 'Покрытие': 'Оцинковка', 'Предел прочности': '640 МПа' },
    matchingTools: 5,
  },
  {
    id: 'P041', name: 'Заклёпки стальные 8х24', article: 'GEN-006', gost: 'ГОСТ 10299-2012', uom: 'тн', quantity: 8,
    domain: 'GENERAL_GOODS', category: 'Крепёж', status: 'to_order', manufacturer: 'ООО Сталь Про', addedDate: '19.04.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 2400,
    description: 'Заклёпки стальные сплошные 8×24 мм для клёпанных конструкций кузовов вагонов.',
    materialId: 'GEN-006-ZAK8', packageQuantity: 500, prevQuantity: 6,
    specifications: { 'Диаметр': '8 мм', 'Длина': '24 мм', 'Материал': 'Сталь 10', 'Прочность': 'ГОСТ соответствие' },
    matchingTools: 2,
  },
  {
    id: 'P042', name: 'Прокладка резиновая ТМКЩ', article: 'GEN-007', gost: 'ГОСТ 15810-2018', uom: 'тн', quantity: 5,
    domain: 'GENERAL_GOODS', category: 'Резина', status: 'in_stock', manufacturer: 'ООО Каучук', addedDate: '21.04.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 5200,
    description: 'Прокладка маслостойкая резиновая техническая ТМКЩ 5-6 мм для герметизации соединений агрегатов локомотивов.',
    materialId: 'GEN-007-PRKL', packageQuantity: 10, prevQuantity: 4,
    specifications: { 'Толщина': '5-6 мм', 'Материал': 'Синтетический каучук', 'Стойкость к маслу': 'Группа III', 'Температура': '-30…+80°C' },
    matchingTools: 3,
  },
  {
    id: 'P043', name: 'Песок кварцевый ПС-1', article: 'GEN-008', gost: 'ГОСТ 8736-2014', uom: 'тн', quantity: 120,
    domain: 'GENERAL_GOODS', category: 'Материалы', status: 'in_stock', manufacturer: 'ООО Кварц Узбек', addedDate: '23.04.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 280,
    description: 'Песок кварцевый ПС-1 фракции 0.8–2.5 мм для фильтрации, абразивной обработки и изготовления литейных форм.',
    materialId: 'GEN-008-PS1', packageQuantity: 100, prevQuantity: 110,
    specifications: { 'Фракция': '0.8–2.5 мм', 'Содержание SiO2': '>98%', 'Содержание FeO': '<0.05%', 'Плотность': '1620 кг/м³' },
    matchingTools: 2,
  },
  {
    id: 'P044', name: 'Масло компрессорное КС-19', article: 'GEN-009', gost: 'ГОСТ 1461-95', uom: 'тн', quantity: 18,
    domain: 'GENERAL_GOODS', category: 'Масла и смазки', status: 'in_stock', manufacturer: 'ООО Масло-Комплекс', addedDate: '25.04.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF', 'C_RATEP'], basePriceFCA: 1850,
    description: 'Масло компрессорное КС-19 для смазки воздушных компрессоров, холодильных агрегатов и вспомогательных машин.',
    materialId: 'GEN-009-KS19', packageQuantity: 25, prevQuantity: 16,
    specifications: { 'Вязкость': '19 сСт при 40°C', 'Температура вспышки': '200°C', 'Кислотное число': '<0.5 мг КОН/г', 'Корозия на медь': '1a' },
    matchingTools: 4,
  },
  {
    id: 'P045', name: 'Фильтр масляный ФМ-22', article: 'GEN-010', gost: 'ТУ 32.144-38-99', uom: 'шт', quantity: 64,
    domain: 'GENERAL_GOODS', category: 'Фильтры', status: 'in_stock', manufacturer: 'АО Фильтр Узбек', addedDate: '27.04.2026',
    ownerCompanyId: 'C_OTHER', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 620,
    description: 'Фильтр масляный навинчиваемый ФМ-22 для локомотивов, применяется в системе смазки тяговых двигателей.',
    materialId: 'GEN-010-FM22', packageQuantity: 8, prevQuantity: 60,
    specifications: { 'Диаметр резьбы': 'М22', 'Ёмкость': '2.2 л', 'Степень очистки': '25 мкм', 'Перепад давления': '0.2–0.6 атм' },
    matchingTools: 3,
  },

  // NEW PRODUCTS: SERVICES (5 items)
  {
    id: 'P046', name: 'Капитальный ремонт ТЭД', article: 'SVC-003', gost: '—', uom: 'комплект', quantity: 12,
    domain: 'SERVICES', category: 'Ремонт и восстановление', status: 'in_stock', manufacturer: 'РТ Сервис', addedDate: '29.04.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 35000,
    description: 'Капитальный ремонт тягового электродвигателя (ТЭД) с полной переборкой, переизоляцией обмоток и испытанием на стенде.',
    materialId: 'SVC-003-TED', packageQuantity: 1, prevQuantity: 10,
    specifications: { 'Включает': 'Разборка, переизоляция, перемотка, испытание, сборка', 'Гарантия': '12 месяцев', 'Срок выполнения': '7–10 рабочих дней', 'Испытание': '2.5 часа на стенде' },
    matchingTools: 4,
  },
  {
    id: 'P047', name: 'Дефектоскопия колёсных пар', article: 'SVC-004', gost: '—', uom: 'комплект', quantity: 24,
    domain: 'SERVICES', category: 'Техническое обслуживание', status: 'in_stock', manufacturer: 'РТ Диагностика', addedDate: '01.05.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 8500,
    description: 'Ультразвуковая дефектоскопия колёсных пар локомотивов и вагонов для выявления трещин и других дефектов.',
    materialId: 'SVC-004-DEFEK', packageQuantity: 1, prevQuantity: 22,
    specifications: { 'Метод': 'Ультразвуковой', 'Охват': 'Полный контроль гребня и боков', 'Чувствительность': 'до 1 мм', 'Протокол': 'С приложением видео' },
    matchingTools: 5,
  },
  {
    id: 'P048', name: 'Сертификация ГОСТ Р', article: 'SVC-005', gost: '—', uom: 'партия', quantity: 6,
    domain: 'SERVICES', category: 'Сертификация', status: 'to_order', manufacturer: 'РТ Сертификация', addedDate: '03.05.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 6200,
    description: 'Получение сертификата соответствия ГОСТ Р для железнодорожной продукции и компонентов подвижного состава.',
    materialId: 'SVC-005-CERT', packageQuantity: 1, prevQuantity: 5,
    specifications: { 'Тип сертификации': 'ГОСТ Р', 'Испытания': 'На аккредитованной лаборатории', 'Срок выдачи': '15–20 рабочих дней', 'Действие сертификата': '3 года' },
    matchingTools: 2,
  },
  {
    id: 'P049', name: 'Техническое освидетельствование', article: 'SVC-006', gost: '—', uom: 'комплект', quantity: 18,
    domain: 'SERVICES', category: 'Инспекция', status: 'in_stock', manufacturer: 'РТ Инспекция', addedDate: '05.05.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 4800,
    description: 'Техническое освидетельствование (ТО) подвижного состава с выдачей паспорта и отметки в журнал ремонтов.',
    materialId: 'SVC-006-TO', packageQuantity: 1, prevQuantity: 16,
    specifications: { 'Включает': 'Визуальный осмотр, испытание тормозов, проверка сцепки, измерения', 'Документ': 'Паспорт ТО', 'Действие': 'Доотечёт перед отправкой' },
    matchingTools: 3,
  },
  {
    id: 'P050', name: 'Пусконаладочные работы', article: 'SVC-007', gost: '—', uom: 'комплект', quantity: 8,
    domain: 'SERVICES', category: 'Пусконаладка', status: 'sourcing', manufacturer: 'РТ Инженерия', addedDate: '07.05.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: false, approvedSellers: ['C_SELF'], basePriceFCA: 12000,
    description: 'Пусконаладочные и монтажные работы для сложного оборудования, включая наладку электросистем и тестирование.',
    materialId: 'SVC-007-PNR', packageQuantity: 1, prevQuantity: 6,
    specifications: { 'Включает': 'Установка, регулировка, электрокоммутация, функциональные тесты', 'Документация': 'Акты наладки, протоколы испытаний', 'Гарантия': '24 месяца' },
    matchingTools: 2,
  },

  // ADDITIONAL PRODUCTS: RailTech Own Products + Variations (5+ items)
  {
    id: 'P051', name: 'Лубрикантный состав РТ-100', article: 'RTS-001', gost: 'ТУ РТ 1.2-18', uom: 'тн', quantity: 30,
    domain: 'GENERAL_GOODS', category: 'Масла и смазки', status: 'in_stock', manufacturer: 'RailTech', addedDate: '10.05.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF', 'C_OTHER'], basePriceFCA: 2950,
    description: 'Собственный синтетический лубрикант РТ-100 для букс и механизмов подвижного состава, повышенная износостойкость.',
    materialId: 'RTS-001-LUB100', packageQuantity: 25, prevQuantity: 28,
    specifications: { 'Тип': 'Синтетический полиолефин', 'Вязкость': '100 сСт при 40°C', 'Температура вспышки': '240°C', 'Противозадирность': 'EP класс' },
    matchingTools: 6,
  },
  {
    id: 'P052', name: 'Трансформаторное масло РТ-45', article: 'RTS-002', gost: 'ГОСТ 982-2016', uom: 'тн', quantity: 45,
    domain: 'GENERAL_GOODS', category: 'Масла и смазки', status: 'in_stock', manufacturer: 'RailTech', addedDate: '12.05.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF', 'C_SAUT', 'C_RATEP'], basePriceFCA: 1650,
    description: 'Высокоочищенное трансформаторное масло марки РТ-45 от RailTech для питающих трансформаторов тяговых подстанций.',
    materialId: 'RTS-002-TRANS45', packageQuantity: 50, prevQuantity: 42,
    specifications: { 'Марка': 'РТ-45', 'Вязкость': '45 мм²/с при 40°C', 'Температура вспышки': '180°C', 'Пробивное напряжение': '>60 кВ' },
    matchingTools: 5,
  },
  {
    id: 'P053', name: 'Электролит для аккумуляторов РТ-АК', article: 'RTS-003', gost: 'ТУ РТ 2.1-19', uom: 'тн', quantity: 12,
    domain: 'GENERAL_GOODS', category: 'Электрохимия', status: 'to_order', manufacturer: 'RailTech', addedDate: '14.05.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF'], basePriceFCA: 4100,
    description: 'Аккумуляторный электролит РТ-АК готовой плотности для свинцовых батарей локомотивов, предварительно смешанный.',
    materialId: 'RTS-003-ELAK', packageQuantity: 20, prevQuantity: 10,
    specifications: { 'Плотность': '1.24 г/см³ при 20°C', 'Концентрация H2SO4': '36–38%', 'Чистота': 'Высокая, без примесей железа', 'Расфасовка': '25 л, 200 л' },
    matchingTools: 3,
  },
  {
    id: 'P054', name: 'Контакт-спрей РТ-50 (аэрозоль)', article: 'RTS-004', gost: '—', uom: 'шт', quantity: 200,
    domain: 'GENERAL_GOODS', category: 'Химия и ЛКМ', status: 'in_stock', manufacturer: 'RailTech', addedDate: '16.05.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: true, approvedSellers: ['C_SELF', 'C_OTHER'], basePriceFCA: 350,
    description: 'Контактный спрей РТ-50 в аэрозольной упаковке для очистки и защиты электрических контактов, разъёмов и реле.',
    materialId: 'RTS-004-SPRAY50', packageQuantity: 12, prevQuantity: 180,
    specifications: { 'Объём баллона': '400 мл', 'Активное вещество': 'Изопропанол с присадками', 'Испаряемость': 'Полная', 'Безопасность': 'Без галогенов' },
    matchingTools: 4,
  },
  {
    id: 'P055', name: 'Тепловыделяющая смазка ТЕПЛОКС РТ', article: 'RTS-005', gost: 'ТУ РТ 3.2-20', uom: 'тн', quantity: 8,
    domain: 'GENERAL_GOODS', category: 'Масла и смазки', status: 'sourcing', manufacturer: 'RailTech', addedDate: '18.05.2026',
    ownerCompanyId: 'C_SELF', partnerVisible: false, approvedSellers: ['C_SELF', 'C_RATEP'], basePriceFCA: 6800,
    description: 'Специализированная термопроводящая смазка ТЕПЛОКС РТ для букс и подшипников с повышенным тепловыделением (эксклюзив).',
    materialId: 'RTS-005-TEPLOX', packageQuantity: 5, prevQuantity: 6,
    specifications: { 'Тип': 'Силиконовая', 'Теплопроводность': '0.85 Вт/м·К', 'Диапазон температур': '-40…+120°C', 'Прилипаемость': 'Повышенная', 'Базовое масло': 'Синтетическое' },
    matchingTools: 2,
  },
];

export const statusLabels: Record<Product['status'], string> = {
  in_stock: 'В наличии',
  to_order: 'Под заказ',
  sourcing: 'Поиск',
  inactive: 'Неактивно',
};

export const domainLabels: Record<Product['domain'], string> = {
  RAILWAY_MACHINERY: 'ЖД и Техника',
  GENERAL_GOODS: 'Общие товары',
  SERVICES: 'Услуги',
};
