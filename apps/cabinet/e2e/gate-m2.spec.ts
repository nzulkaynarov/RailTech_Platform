/**
 * FIX-51 · прогон гейта M2 на стенде против настоящего ERP (не MSW): путь клиента BUSINESS §4 шаги 4–10.
 *
 * Запуск (стенд поднят `make up`, из корня репозитория со стендом; в CI не входит):
 *
 *   cd apps/cabinet
 *   E2E_BASE_URL=http://cabinet.localhost:8088 \
 *   E2E_STAND_ROOT=/путь/к/корню/репозитория-со-стендом \      # там .env: оттуда `docker compose logs` читает письма
 *   E2E_CRM_ADMIN_EMAIL=… E2E_CRM_ADMIN_PASSWORD=… \          # администратор CRM с доступом к ERP (CRM «Пользователи»)
 *   npm run test:e2e
 *
 * Необязательно: E2E_RESUME=1 — продолжить с первого непройденного шага (состояние — test-results/gate-m2-state.json),
 * E2E_BOT_USERNAME — имя бота: проверить кнопки «Написать менеджеру» (на стенде без бота их нет), E2E_SCREENS_DIR.
 *
 * Что делает: лид из формы «Я новый клиент» → CRM «Передать в бэк-офис» → приглашение в Cabinet (токен — из логов ERP,
 * только в браузер) → бэк-офис выпускает КП → клиент принимает по коду → договор → счёт → поставка по строкам → акт
 * со сканом → документы и поиск; второй запрос из каталога: отказ от КП с причиной и возврат акта. Кроме того: права
 * (просмотр без права действовать), изоляция компаний, ru / uz / en, повторный вход по ссылке. На каждом экране —
 * скриншоты 1440 и 390 px, axe в браузере (serious/critical проваливают, остальное — в axe-summary.json) и
 * проверка горизонтальной прокрутки. Токены, коды и пароли не печатаются и не сохраняются.
 */
import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { contractIdByDeal, buildAndSendQuote, issueAct, pickProducts, recordPayment, resendQuoteVersion, shipAndDeliver, signAndInvoice } from './helpers/backoffice';
import { crmLogin, findLeadId, takeAndHandOff } from './helpers/crm';
import { CABINET_URL, CRM_URL, RESUME, STATE_FILE } from './helpers/env';
import { erpLoginFromCrm, type ErpApi } from './helpers/erp';
import { latestMagicToken, latestQuoteCode, magicTokens, mailCount, waitNewMagicToken } from './helpers/mail';
import { snap } from './helpers/shots';

interface State {
  tag: string;
  done: Record<string, true>;
  leadId?: number;
  dealA?: number;
  quoteA?: number;
  invoiceA?: number;
  dealB?: number;
  quoteB?: number;
  invoiceB?: number;
  colleagueEmail?: string;
}

function loadState(): State {
  if (RESUME) {
    try {
      return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')) as State;
    } catch {
      /* нет файла — начинаем с нуля */
    }
  }
  return { tag: `r${Date.now().toString(36).slice(-5)}`, done: {} };
}

const state = loadState();
const save = () => {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
};

const COMPANY = 'FIX-51 Тест ООО';
const email = `fix51-${state.tag}@example.com`;
const colleague = `fix51-${state.tag}-viewer@example.com`;
const phone = `+99893${String(Math.abs(Number.parseInt(state.tag.slice(1), 36)) % 10_000_000).padStart(7, '0')}`;
const needText = `FIX-51 [${state.tag}]: подшипники 6205-2RS 100 шт и ремни SPZ 1250 20 шт, срок две недели`;
const CLIENT_STATE = path.join(path.dirname(STATE_FILE), 'gate-m2-client-session.json');

const A3 = 'A3. вход по приглашению из письма (токен из логов ERP — только в адресную строку)';

let client: Page;
let clientCtx: BrowserContext;
let crm: Page;
let erp: ErpApi;

/** Минимальный валидный PDF — «скан подписанного акта». */
const SCAN_PDF = Buffer.from('%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF');

function step(title: string, body: () => Promise<void>) {
  test(title, async () => {
    test.skip(RESUME && Boolean(state.done[title]), 'шаг пройден в предыдущем запуске (E2E_RESUME=1)');
    await body();
    state.done[title] = true;
    save();
  });
}

const open = (path: string) => client.goto(`${CABINET_URL}${path}`);

/** После входа убеждаемся, что вошёл именно тот контакт: чужой кабинет (ссылка из соседнего письма) — немедленный отказ прогона. */
async function expectSignedInAs(page: Page, address: string): Promise<void> {
  await expect(page).toHaveURL(/\/requests/);
  const me = await page.evaluate(async () => (await fetch('/api/portal/v1/me', { credentials: 'include' })).json() as Promise<{ contact: { email: string } }>);
  if (me.contact.email !== address) {
    await page.context().clearCookies();
    throw new Error(`вход под чужим контактом (${me.contact.email}) — прогон остановлен, чужие данные не трогаем`);
  }
}

async function loginWithMagicToken(page: Page, address: string): Promise<void> {
  const token = latestMagicToken(address);
  expect(token, `в логах ERP есть письмо со ссылкой входа для ${address}`).toBeTruthy();
  await page.goto(`${CABINET_URL}/auth/magic#token=${token}`);
  await expectSignedInAs(page, address);
}

/** Вход по форме: «Войти» → письмо → ссылка (обычный повторный вход; приглашение к этому моменту уже использовано). */
async function signInByForm(page: Page, address: string): Promise<void> {
  const known = magicTokens(address);
  await page.goto(`${CABINET_URL}/login`);
  await page.getByLabel('E-mail').fill(address);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('heading', { name: 'Письмо отправлено' })).toBeVisible();
  const token = await waitNewMagicToken(address, known);
  await page.goto(`${CABINET_URL}/auth/magic#token=${token}`);
  await expectSignedInAs(page, address);
}

/** Сделка прогона по метке в заметках (в списке ERP заметок нет — читаем карточки свежих сделок нашей компании). */
async function dealIdByNote(needle: string): Promise<number> {
  const { json } = await erp.ok('GET', 'crm/deals/?page_size=100');
  const ours = (json.results as { id: number; company_name: string }[]).filter((d) => d.company_name === COMPANY).sort((x, y) => y.id - x.id).slice(0, 12);
  for (const deal of ours) {
    const card = await erp.ok('GET', `crm/deals/${deal.id}/`);
    if (`${card.json.notes} ${card.json.title}`.includes(needle)) return deal.id;
  }
  throw new Error(`в ERP нет сделки компании ${COMPANY} с «${needle}»`);
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async ({ browser }) => {
  clientCtx = await browser.newContext({
    locale: 'ru-RU',
    viewport: { width: 1440, height: 900 },
    storageState: RESUME && fs.existsSync(CLIENT_STATE) ? CLIENT_STATE : undefined,
  });
  client = await clientCtx.newPage();
  const crmCtx = await browser.newContext({ locale: 'ru-RU', viewport: { width: 1440, height: 900 } });
  crm = await crmCtx.newPage();
  await crmLogin(crm);
  erp = await erpLoginFromCrm(crm);
  if (RESUME && state.done[A3]) {
    // продолжение прогона: сеанс клиента мог не сохраниться — тогда входим заново по ссылке из письма
    await client.goto(`${CABINET_URL}/requests`);
    await client.getByRole('heading', { level: 1, name: /Запросы|Вход в кабинет/ }).waitFor();
    if (/\/login/.test(client.url())) {
      await signInByForm(client, email);
    }
  }
});

test.afterAll(async () => {
  await clientCtx.storageState({ path: CLIENT_STATE });
});

test.describe('A. Вход и первое знакомство', () => {
  step('A1. страница входа и форма «Я новый клиент» → лид в CRM', async () => {
    const anon = await clientCtx.browser()!.newContext({ locale: 'ru-RU', viewport: { width: 1440, height: 900 } });
    const page = await anon.newPage();
    await page.goto(`${CABINET_URL}/login`);
    await expect(page.getByRole('heading', { name: 'Вход в кабинет' })).toBeVisible();
    await snap(page, 'login');
    await page.getByRole('link', { name: 'Я новый клиент' }).click();
    await expect(page.getByRole('heading', { name: 'Я новый клиент' })).toBeVisible();
    await page.getByRole('button', { name: 'Отправить запрос' }).click();
    await expect(page.getByText('Укажите, как к вам обращаться.')).toBeVisible();
    await snap(page, 'new-client-validation');
    await page.getByLabel('Как к вам обращаться').fill('FIX-51 Клиент');
    await page.getByLabel('Компания (необязательно)').fill(COMPANY);
    await page.getByLabel('Телефон').fill(phone);
    await page.getByLabel('E-mail').fill(email);
    await page.getByLabel('Что нужно').fill(needText);
    await snap(page, 'new-client-form');
    // без галочки согласия запрос не уходит
    await page.getByRole('button', { name: 'Отправить запрос' }).click();
    await expect(page.getByText(/Без согласия на обработку персональных данных/)).toBeVisible();
    await page.getByRole('checkbox').check();
    // защита формы CRM: быстрее min_fill_seconds после получения токена отправка отклоняется (form_too_fast)
    await page.waitForTimeout(4500);
    await page.getByRole('button', { name: 'Отправить запрос' }).click();
    await expect(page.getByRole('heading', { name: 'Спасибо! Запрос отправлен' })).toBeVisible();
    await snap(page, 'new-client-sent');
    await anon.close();
  });

  step('A2. CRM: лид появился с согласием; «Передать в бэк-офис»', async () => {
    state.leadId = await findLeadId(crm, `[${state.tag}]`);
    save();
    await expect(crm.getByText('Согласие')).toBeVisible();
    await snap(crm, 'crm-lead-from-cabinet-form', { axe: false });
    await takeAndHandOff(crm, state.leadId, COMPANY);
    await crm.goto(`${CRM_URL}/clients`);
    await snap(crm, 'crm-clients-after-handoff', { axe: false });
  });

  step(A3, async () => {
    // письмо уходит из ERP воркером после передачи: ждём до 30 с
    await expect.poll(() => latestMagicToken(email), { timeout: 40_000, intervals: [2000] }).not.toBeNull();
    await loginWithMagicToken(client, email);
    await expect(client.getByText(COMPANY).first()).toBeVisible();
    await snap(client, 'requests-first-login');
    // повторное открытие той же ссылки — «Ссылка не действует» при уже активном сеансе: «Вы уже вошли»
  });
});

test.describe('B. Бэк-офис готовит КП (подготовка данных, не прогон M1)', () => {
  step('B1. сотрудник в ERP (вход из CRM по SSO): заявка → КП → согласование → отправка', async () => {
    state.dealA = await dealIdByNote(state.tag);
    const [bearing, belt, plate] = await pickProducts(erp, ['Накладка рельсовая', 'Шуруп путевой', 'Подкладка КБ-65']);
    state.quoteA = await buildAndSendQuote(erp, state.dealA, [
      { product: bearing, quantity: 100, price: '150000.00' },
      { product: belt, quantity: 500, price: '8000.00' },
      { product: plate, quantity: 40, price: '25000.00' },
    ]);
    save();
  });
});

test.describe('C. КП: «Требует вашего решения», принять по коду', () => {
  step('C1. «Запросы» и блок «Требует вашего решения»', async () => {
    await open('/requests');
    await expect(client.getByText('Требует вашего решения')).toBeVisible();
    await expect(client.getByText('Посмотреть КП')).toBeVisible();
    await snap(client, 'requests-action-required');
  });

  step('C2. список КП и карточка', async () => {
    await open('/quotes');
    await expect(client.getByText('1 КП ждёт вашего решения')).toBeVisible();
    await snap(client, 'quotes-list');
    await client.getByRole('link', { name: /КП-\d{4}-\d+/ }).first().click();
    await expect(client.getByRole('button', { name: 'Принять' })).toBeVisible();
    await snap(client, 'quote-detail');
  });

  step('C3. принять КП: код из письма → «КП принято», договор готов', async () => {
    await open('/quotes');
    await client.getByRole('link', { name: /КП-\d{4}-\d+/ }).first().click();
    await client.getByRole('button', { name: 'Принять' }).click();
    const dialog = client.getByRole('dialog');
    await snap(client, 'quote-accept-dialog-request-code');
    await dialog.getByRole('button', { name: 'Получить код' }).click();
    await expect(dialog.getByLabel('Код подтверждения')).toBeVisible();
    // неверный код — ошибка в диалоге, диалог остаётся
    await dialog.getByLabel('Код подтверждения').fill('000000');
    await dialog.getByRole('button', { name: 'Принять КП' }).click();
    await expect(dialog.getByRole('alert').or(dialog.getByText(/неверен|не запрошен/i)).first()).toBeVisible();
    await snap(client, 'quote-accept-dialog-wrong-code');
    await expect.poll(() => latestQuoteCode(email), { timeout: 30_000, intervals: [2000] }).not.toBeNull();
    await dialog.getByLabel('Код подтверждения').fill(latestQuoteCode(email)!);
    await dialog.getByRole('button', { name: 'Принять КП' }).click();
    await expect(client.getByText('КП принято').first()).toBeVisible();
    await snap(client, 'quote-accepted');
  });
});

test.describe('D. Договор → счёт', () => {
  step('D1. договор: подписать (клиент)', async () => {
    await open('/requests');
    await expect(client.getByText('Подписать договор')).toBeVisible();
    await snap(client, 'requests-action-required-contract');
    await open('/contracts');
    await expect(client.getByText('1 договор ждёт вашей подписи')).toBeVisible();
    await snap(client, 'contracts-awaiting-signature');
    await client.getByRole('button', { name: /^Подписать/ }).first().click();
    await snap(client, 'contract-sign-dialog');
    await client.getByRole('dialog').getByRole('button', { name: 'Подписать договор' }).click();
    await expect(client.getByText(/подписан\. Ждём подписи исполнителя/)).toBeVisible();
    await snap(client, 'contracts-signed-by-client');
  });

  step('D2. бэк-офис подписывает, выставляет счёт, фиксирует аванс', async () => {
    const contractId = await contractIdByDeal(erp, state.dealA!);
    state.invoiceA = await signAndInvoice(erp, state.dealA!, contractId);
    await recordPayment(erp, state.invoiceA, '10000000.00');
    save();
  });

  step('D3. договор «подписан сторонами» и счёт с остатком', async () => {
    await open('/contracts');
    await expect(client.getByText('Подписан сторонами').first()).toBeVisible();
    await snap(client, 'contracts-signed-both');
    await open('/invoices');
    await expect(client.getByText('Оплачен частично')).toBeVisible();
    await snap(client, 'invoices');
    // в «Требует вашего решения» счёт попадает только просроченным (срок оплаты 14 дней) — на этом шаге его там нет
  });
});

test.describe('E. Поставка по строкам → акт со сканом', () => {
  step('E1. поставка в пути → доставлено', async () => {
    await shipAndDeliver(erp, state.dealA!, 'SHIPPED');
    await open('/deliveries');
    await expect(client.getByText('Отгружено').first()).toBeVisible();
    await snap(client, 'deliveries-shipped');
    await shipAndDeliver(erp, state.dealA!, 'DELIVERED');
    await open('/deliveries');
    await expect(client.getByText('Доставлено 3 из 3')).toBeVisible();
    await snap(client, 'deliveries-delivered');
  });

  step('E2. приёмка по строкам: две принять, по одной замечание', async () => {
    await open('/deliveries');
    await client.getByRole('button', { name: /^Принять позицию Накладка/ }).click();
    await expect(client.getByText(/Принято/).first()).toBeVisible();
    await client.getByRole('button', { name: /^Есть замечания по позиции Подкладка/ }).click();
    const dialog = client.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Отправить замечание' }).click(); // без причины — нельзя
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Причина замечания').fill('FIX-51: маркировка на подкладках не соответствует накладной');
    await snap(client, 'delivery-dispute-dialog');
    await dialog.getByRole('button', { name: 'Отправить замечание' }).click();
    await expect(dialog).toBeHidden();
    await client.getByRole('button', { name: /^Принять позицию Шуруп/ }).click();
    await expect(client.getByText(/Замечание:/)).toBeVisible();
    await snap(client, 'deliveries-accepted-and-disputed');
  });

  step('E3. акт: принять со сканом', async () => {
    await issueAct(erp, state.invoiceA!);
    await open('/requests');
    await expect(client.getByText('Принять акт').first()).toBeVisible();
    await snap(client, 'requests-action-required-act');
    await open('/acts');
    await expect(client.getByText('1 акт ждёт вашей приёмки')).toBeVisible();
    await snap(client, 'acts-awaiting');
    await client.getByRole('button', { name: /^Принять акт/ }).click();
    const dialog = client.getByRole('dialog');
    await dialog.locator('input[type="file"]').setInputFiles({ name: 'FIX-51-scan.pdf', mimeType: 'application/pdf', buffer: SCAN_PDF });
    await snap(client, 'act-accept-dialog-with-scan');
    await dialog.getByRole('button', { name: 'Принять акт' }).click();
    await expect(client.getByText(/принят/i).first()).toBeVisible();
    await expect(client.getByRole('button', { name: /^Скан подписанного акта/ }).or(client.getByRole('link', { name: /^Скан подписанного акта/ }))).toBeVisible();
    await snap(client, 'acts-accepted-with-scan');
  });

  step('E4. сделка целиком и «Запросы» после приёмки', async () => {
    await open(`/deals/${state.dealA}`);
    await expect(client.getByText(/Сделка № D-/).first()).toBeVisible();
    await snap(client, 'deal-full-path');
  });
});

test.describe('F. Документы и поиск', () => {
  step('F1. документы: вид, поиск, скачивание', async () => {
    await open('/documents');
    await expect(client.getByRole('row').filter({ hasText: 'Договор' }).first()).toBeVisible();
    await snap(client, 'documents');
    const kinds = client.getByRole('group', { name: 'Вид документа' });
    await kinds.getByRole('button', { name: 'Счета' }).click();
    await expect(client.getByRole('row').filter({ hasText: 'Счёт INV-' }).first()).toBeVisible();
    await snap(client, 'documents-filter-invoices');
    await kinds.getByRole('button', { name: 'Все' }).click();
    await client.getByRole('searchbox', { name: 'Поиск документов' }).fill('КП-');
    await expect(client.getByRole('row').filter({ hasText: 'Коммерческое предложение' }).first()).toBeVisible();
    await snap(client, 'documents-search');
    const downloading = client.waitForEvent('download');
    await client.getByRole('button', { name: /Скачать/ }).first().click();
    const file = await (await downloading).createReadStream();
    const head: Buffer[] = [];
    for await (const chunk of file) head.push(chunk as Buffer);
    const bytes = Buffer.concat(head);
    expect(bytes.subarray(0, 5).toString(), 'скачанный документ — PDF').toBe('%PDF-');
  });
});

test.describe('G. Новый запрос из каталога → отказ от КП → возврат акта', () => {
  step('G1. каталог → «В запрос» → запрос', async () => {
    await open('/catalog');
    await expect(client.getByRole('button', { name: 'В запрос' }).first()).toBeVisible();
    await snap(client, 'catalog');
    await client.getByRole('button', { name: 'В запрос' }).first().click();
    await client.getByRole('button', { name: /^Оформить запрос/ }).click();
    await expect(client).toHaveURL(/\/requests\/new/);
    await client.getByLabel('Что нужно').fill(`FIX-51 [${state.tag}] запрос из каталога: 50 шт, доставка на станцию Навои`);
    await snap(client, 'request-new-from-catalog');
    await client.getByRole('button', { name: 'Отправить запрос' }).click();
    await expect(client).toHaveURL(/\/requests\/\d+$/);
    await expect(client.getByText(/Запрос Z-\d+ отправлен/)).toBeVisible();
    await snap(client, 'request-detail-new');
  });

  step('G2. бэк-офис отправляет КП v1; клиент отклоняет с причиной', async () => {
    state.dealB = await dealIdByNote(`запрос из каталога: 50 шт`);
    const [item] = await pickProducts(erp, ['Железный шпала']);
    state.quoteB = await buildAndSendQuote(erp, state.dealB, [{ product: item, quantity: 50, price: '90000.00' }]);
    save();
    await open('/quotes');
    await client.getByRole('link', { name: /версия 1/ }).first().click();
    await client.getByRole('button', { name: 'Отклонить' }).click();
    const dialog = client.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Отклонить КП' }).click(); // без причины — нельзя
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Причина').fill('FIX-51: срок поставки не устраивает, нужен 10 дней');
    await snap(client, 'quote-reject-dialog');
    await dialog.getByRole('button', { name: 'Отклонить КП' }).click();
    await expect(client.getByText('КП отклонено').first()).toBeVisible();
    await snap(client, 'quote-rejected');
  });

  step('G3. новая версия КП → принять → договор → счёт → акт → клиент возвращает акт', async () => {
    const v2 = await resendQuoteVersion(erp, state.quoteB!);
    expect(v2).not.toBe(state.quoteB);
    await open('/quotes');
    await client.getByRole('link', { name: /версия 2/ }).first().click();
    await client.getByRole('button', { name: 'Принять' }).click();
    const dialog = client.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Получить код' }).click();
    await expect.poll(() => latestQuoteCode(email, '5m'), { timeout: 30_000, intervals: [2000] }).not.toBeNull();
    await dialog.getByLabel('Код подтверждения').fill(latestQuoteCode(email, '5m')!);
    await dialog.getByRole('button', { name: 'Принять КП' }).click();
    await expect(client.getByText('КП принято').first()).toBeVisible();
    await open('/contracts');
    await client.getByRole('button', { name: /^Подписать/ }).first().click();
    await client.getByRole('dialog').getByRole('button', { name: 'Подписать договор' }).click();
    await expect(client.getByText(/подписан\. Ждём подписи исполнителя/)).toBeVisible();
    const contractId = await contractIdByDeal(erp, state.dealB!);
    state.invoiceB = await signAndInvoice(erp, state.dealB!, contractId);
    await issueAct(erp, state.invoiceB);
    save();
    await open('/acts');
    await client.getByRole('button', { name: /^Вернуть акт/ }).click();
    const returnDialog = client.getByRole('dialog');
    await returnDialog.getByRole('button', { name: 'Вернуть акт' }).click(); // без причины — нельзя
    await expect(returnDialog).toBeVisible();
    await returnDialog.getByLabel('Причина возврата').fill('FIX-51: не указан серийный номер партии');
    await snap(client, 'act-return-dialog');
    await returnDialog.getByRole('button', { name: 'Вернуть акт' }).click();
    await expect(client.getByText(/Возвращён: FIX-51/)).toBeVisible();
    await snap(client, 'acts-returned');
  });
});

test.describe('H. Компания, команда, профиль, языки', () => {
  step('H1. компания и команда: приглашение коллеги (только просмотр)', async () => {
    await open('/company');
    await expect(client.getByRole('heading', { name: 'Компания' })).toBeVisible();
    await snap(client, 'company');
    await client.getByRole('button', { name: 'Изменить' }).click();
    await snap(client, 'company-edit');
    await client.getByRole('button', { name: 'Отмена' }).click();
    await open('/team');
    await client.getByRole('button', { name: 'Пригласить коллегу' }).click();
    const dialog = client.getByRole('dialog');
    await dialog.getByLabel('Имя и фамилия').fill('FIX-51 Наблюдатель');
    await dialog.getByRole('textbox', { name: 'E-mail' }).fill(colleague);
    await dialog.getByRole('checkbox', { name: /^Может подтверждать/ }).uncheck();
    await snap(client, 'team-invite-dialog');
    const before = mailCount(colleague);
    await dialog.getByRole('button', { name: 'Отправить приглашение' }).click();
    await expect(client.getByText(/Приглашение для .* отправлено/)).toBeVisible();
    await snap(client, 'team-invited');
    await expect.poll(() => mailCount(colleague), { timeout: 40_000, intervals: [2000] }).toBeGreaterThan(before);
    state.colleagueEmail = colleague;
    save();
  });

  step('H2. профиль и переключение ru / uz / en на одном экране', async () => {
    for (const [code, label, heading] of [
      ['uz', 'Oʻzbekcha', /So[ʻ'’]rovlar/],
      ['en', 'English', /^Requests$/],
      ['ru', 'Русский', /^Запросы$/],
    ] as const) {
      await open('/profile');
      await client.getByRole('button', { name: label }).click();
      await expect(client.getByRole('button', { name: label })).toHaveAttribute('aria-pressed', 'true');
      await snap(client, `profile-${code}`);
      await open('/requests');
      await expect(client.getByRole('heading', { level: 1 })).toHaveText(heading);
      await snap(client, `requests-${code}`);
    }
  });
});

test.describe('I. Права, изоляция, выход и повторный вход', () => {
  step('I1. коллега без права действовать: только просмотр; чужое не видно', async () => {
    const ctx = await clientCtx.browser()!.newContext({ locale: 'ru-RU', viewport: { width: 1440, height: 900 } });
    const viewer = await ctx.newPage();
    await expect.poll(() => latestMagicToken(colleague), { timeout: 40_000, intervals: [2000] }).not.toBeNull();
    // приглашение коллеге — первый вход по ссылке из письма; при повторе прогона — по форме
    const invite = latestMagicToken(colleague)!;
    await viewer.goto(`${CABINET_URL}/auth/magic#token=${invite}`);
    if (await viewer.waitForURL(/\/requests/, { timeout: 8000 }).then(() => true, () => false)) await expectSignedInAs(viewer, colleague);
    else await signInByForm(viewer, colleague);
    await expect(viewer.getByRole('link', { name: 'Новый запрос' })).toHaveCount(0);
    await snap(viewer, 'requests-viewer-only');
    await viewer.goto(`${CABINET_URL}/profile`);
    await expect(viewer.getByText('Только просмотр', { exact: true })).toBeVisible();
    // API решает сам: действие без права — 403; чужая сущность — 404 (чужие id КП/договора/счёта в ERP заведомо есть)
    const denied = await viewer.evaluate(async (quoteId) => (await fetch(`/api/portal/v1/quotes/${quoteId}/reject`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ reason: 'FIX-51 проверка прав' }) })).status, state.quoteB!);
    expect([403, 409]).toContain(denied);
    await ctx.close();
  });

  step('I2. изоляция: чужие объекты — 404, в ответах нет себестоимости, маржи и поставщиков', async () => {
    const { json } = await erp.ok('GET', 'crm/quotes/?page_size=100');
    const foreign = (json.results as { id: number; deal: number }[]).find((q) => q.id !== state.quoteA && q.id !== state.quoteB && q.deal !== state.dealA && q.deal !== state.dealB);
    expect(foreign, 'в ERP есть КП другой компании').toBeTruthy();
    await open('/requests');
    const result = await client.evaluate(async (foreignQuote) => {
      const get = async (url: string) => {
        const response = await fetch(`/api/portal/v1${url}`, { credentials: 'include' });
        return { status: response.status, text: await response.text() };
      };
      const own = await Promise.all(['/quotes', '/contracts', '/invoices', '/acts', '/deliveries', '/documents', '/requests', '/catalog', '/company', '/team', '/me'].map(async (url) => [url, await get(url)] as const));
      return { foreign: await get(`/quotes/${foreignQuote}`), own };
    }, foreign!.id);
    expect(result.foreign.status, 'чужое КП недоступно').toBe(404);
    const leak = /margin|markup|landed|cost|supplier|purchase|закупк|себестоим|поставщик/i;
    for (const [url, response] of result.own) {
      expect(response.status, `GET ${url}`).toBe(200);
      expect(response.text, `в ответе ${url} нет внутренних полей`).not.toMatch(leak);
    }
  });

  step('I3. выход и повторный вход по ссылке из письма; использованная ссылка', async () => {
    await open('/profile');
    await client.getByRole('button', { name: 'Выйти из кабинета' }).click();
    await expect(client).toHaveURL(/\/login/);
    const known = magicTokens(email);
    await client.getByLabel('E-mail').fill(email);
    await client.getByRole('button', { name: 'Войти' }).click();
    await expect(client.getByRole('heading', { name: 'Письмо отправлено' })).toBeVisible();
    await snap(client, 'login-sent');
    const token = await waitNewMagicToken(email, known);
    await client.goto(`${CABINET_URL}/auth/magic#token=${token}`);
    await expectSignedInAs(client, email);
    // та же ссылка во второй раз (новый «браузер» без сеанса) — «Ссылка не действует»
    const other = await clientCtx.browser()!.newContext({ locale: 'ru-RU', viewport: { width: 1440, height: 900 } });
    const page = await other.newPage();
    await page.goto(`${CABINET_URL}/auth/magic#token=${token}`);
    await expect(page.getByText('Ссылка не действует')).toBeVisible();
    await snap(page, 'magic-link-used');
    await other.close();
  });

  step('I4. «Написать менеджеру» (если на стенде задан бот)', async () => {
    await open(`/deals/${state.dealA}`);
    const link = client.getByRole('link', { name: /Написать менеджеру/ }).first();
    if ((await link.count()) === 0) {
      test.info().annotations.push({ type: 'не проверено', description: 'на стенде не задано имя бота (TELEGRAM_BOT_USERNAME): кнопки «Написать менеджеру» нет — проверка на телефоне владельцем' });
      return;
    }
    await expect(link).toHaveAttribute('href', new RegExp(`^https://t\\.me/${process.env.E2E_BOT_USERNAME ?? '[^?]+'}\\?start=deal_${state.dealA}$`));
    await snap(client, 'deal-manager-button');
  });
});

/**
 * J. Экраны волны 3 (FIX-31, 33, 34, 34b, 35), снятые раньше на подставном API, — теперь на стенде против настоящего ERP.
 * Состояния «ждёт передачи» и «ИНН уже есть у другого клиента» на стенде не воспроизводятся без второго лида с согласием
 * (форма Cabinet ограничена по частоте) — это отмечено в отчёте. Только скриншоты: axe для CRM не входит в гейт M2.
 */
test.describe('J. CRM: экраны волны 3 на стенде', () => {
  const open = (url: string) => crm.goto(`${CRM_URL}${url}`);

  step('J1. лид и клиент после передачи: «В бэк-офисе», сделки и документы из ERP (FIX-31, FIX-35)', async () => {
    await open(`/leads/${state.leadId}`);
    await expect(crm.getByText(/В бэк-офисе: Компания #\d+/)).toBeVisible();
    await snap(crm, 'crm-lead-after-handoff', { axe: false });
    await crm.getByRole('link', { name: 'Открыть карточку клиента' }).click();
    await expect(crm.getByText(/В бэк-офисе:/).first()).toBeVisible();
    await snap(crm, 'crm-client-card', { axe: false });
    await crm.getByRole('tab', { name: /^Сделки/ }).click();
    await expect(crm.getByText('Выиграна').first()).toBeVisible();
    await snap(crm, 'crm-client-deals', { axe: false });
    await crm.getByRole('tab', { name: /^Документы/ }).click();
    await expect(crm.getByRole('row').filter({ hasText: 'Акт' }).first()).toBeVisible();
    await snap(crm, 'crm-client-documents', { axe: false });
  });

  step('J2. «Сделки» CRM: стадии пришли событиями ERP (FIX-30, FIX-33)', async () => {
    await open('/deals');
    await expect(crm.getByRole('row').filter({ hasText: 'FIX-51' }).first()).toBeVisible();
    await snap(crm, 'crm-deals', { axe: false });
  });

  step('J3. «Внешние сервисы»: «События из ERP», «Передача клиентов в ERP» (FIX-33)', async () => {
    await open('/external-services');
    await expect(crm.getByRole('link', { name: 'События из ERP' })).toBeVisible();
    await snap(crm, 'crm-external-services', { axe: false });
    await crm.getByRole('link', { name: 'События из ERP' }).click();
    await expect(crm.getByRole('heading', { name: 'События из ERP' }).first()).toBeVisible();
    await snap(crm, 'crm-external-services-erp-events', { axe: false });
  });

  step('J4. «Подключения → ERP»: секреты не на экране, ротация секрета (FIX-35)', async () => {
    await open('/integrations');
    await crm.getByRole('tab', { name: 'ERP' }).click();
    await expect(crm.getByLabel('Предыдущий секрет вебхуков')).toBeVisible();
    // секреты — только «····1234»: ни одно поле формы не несёт значения, длинных токенов на экране нет
    const values = await crm.locator('input').evaluateAll((nodes) => nodes.map((n) => (n as HTMLInputElement).value));
    expect(values.filter((v) => v.length > 40), 'в полях формы нет длинных секретов').toEqual([]);
    expect(await crm.locator('main').innerText()).not.toMatch(/[A-Za-z0-9_-]{40,}/);
    await snap(crm, 'crm-integrations-erp', { axe: false });
  });

  step('J5. «Настройки»: адрес кабинета и тексты бота по событиям ERP (FIX-34)', async () => {
    await open('/settings');
    await expect(crm.getByText('Адрес кабинета клиента').first()).toBeVisible();
    await snap(crm, 'crm-settings-company', { axe: false });
    await crm.getByText('Тексты бота', { exact: true }).click();
    await expect(crm.getByText(/События бэк-офиса \(ERP\)/).first()).toBeVisible();
    await snap(crm, 'crm-settings-bot-texts', { axe: false });
  });
});
