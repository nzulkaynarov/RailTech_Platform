/**
 * FIX-51 / FIX-51b · прогон гейта M2 на стенде против настоящего ERP (не MSW): путь клиента BUSINESS §4 шаги 4–10.
 * FIX-51b — повтор после раунда 2 (FIX-54…58): проверки исправлений D-1, D-2, D-4…D-10, C-9, I-26, картинки каталога.
 *
 * Запуск (стенд поднят `make up`, из корня репозитория со стендом; в CI не входит):
 *
 *   cd apps/cabinet
 *   E2E_BASE_URL=http://cabinet.localhost:8088 \
 *   E2E_STAND_ROOT=/путь/к/корню/репозитория-со-стендом \      # там .env: оттуда `docker compose logs` читает письма
 *   E2E_CRM_ADMIN_EMAIL=… E2E_CRM_ADMIN_PASSWORD=… \          # администратор CRM с доступом к ERP (CRM «Пользователи»)
 *   npm run test:e2e
 *
 * Необязательно: E2E_RESUME=1 — продолжить с первого непройденного шага (состояние — node_modules/.cache/gate-m2/state.json),
 * E2E_BOT_USERNAME — имя бота: проверить кнопки «Написать менеджеру» (на стенде без бота их нет), E2E_SCREENS_DIR.
 *
 * Что делает: переход «В бэк-офис (ERP)» из CRM в чистом браузере 10 раз подряд (без обходов) → лид из формы «Я новый клиент»
 * → CRM «Передать в бэк-офис» → приглашение в Cabinet (токен — из логов ERP, только в браузер) → бэк-офис выпускает КП →
 * клиент принимает по коду → договор → счёт → поставка по строкам → акт со сканом → документы и поиск; второй запрос из
 * каталога: отказ от КП с причиной и возврат акта. Отдельно: ручной лид CRM без согласия → «Согласие получено» → передача.
 * Кроме того: права (просмотр без права действовать), изоляция компаний, ru / uz / en, повторный вход по ссылке. На каждом
 * экране — скриншоты 1440 и 390 px, axe в браузере (serious/critical проваливают, остальное — в axe-summary.json) и
 * проверка горизонтальной прокрутки. Токены, коды и пароли не печатаются и не сохраняются.
 */
import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { contractIdByDeal, buildAndSendQuote, issueAct, pickProducts, recordPayment, resendQuoteVersion, shipAndDeliver, signAndInvoice } from './helpers/backoffice';
import { createClient, createConsentedLead, crmLogin, crmLoginAs, findLeadId, handoffToExistingClient, leadAction, resetStaffPassword, takeAndHandOff } from './helpers/crm';
import { CABINET_URL, CRM_URL, RESUME, STATE_FILE } from './helpers/env';
import { clickThroughToErp, erpLoginFromCrm, type ErpApi, type SsoOutcome } from './helpers/erp';
import { latestMagicToken, latestQuoteCode, logLines, magicTokens, mailCount, waitNewMagicToken } from './helpers/mail';
import { sleeperPng } from './helpers/png';
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
  manualLeadId?: number;
  photoProduct?: number;
  photoId?: number;
  sso?: string;
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
/** Начало этого запуска: окно журналов контейнеров для проверок «ошибки в логе нет». */
const RUN_START = new Date().toISOString();
const save = () => {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
};

const COMPANY = 'FIX-51b Тест ООО';
const MANUAL_COMPANY = 'FIX-51b Звонок ООО';
const email = `fix51b-${state.tag}@example.com`;
const colleague = `fix51b-${state.tag}-viewer@example.com`;
const phone = `+99893${String(Math.abs(Number.parseInt(state.tag.slice(1), 36)) % 10_000_000).padStart(7, '0')}`;
const manualPhone = `+99894${String(Math.abs(Number.parseInt(state.tag.slice(1), 36)) % 10_000_000).padStart(7, '0')}`;
const needText = `FIX-51b [${state.tag}]: подшипники 6205-2RS 100 шт и ремни SPZ 1250 20 шт, срок две недели`;
const CLIENT_STATE = path.join(path.dirname(STATE_FILE), 'gate-m2-client-session.json');

const A3 = 'A3. вход по приглашению из письма (токен из логов ERP — только в адресную строку)';

let client: Page;
let clientCtx: BrowserContext;
let crm: Page;
let erp: ErpApi;
/** Сотрудник «FIX-51 Менеджер»: ведёт КП (автор), а `erp` (администратор) согласует — автор не согласует своё КП (FIX-55, D-02). */
let manager: ErpApi;
const MANAGER_EMAIL = 'fix51-manager@example.com';

/** Минимальный валидный PDF — «скан подписанного акта». */
const SCAN_PDF = Buffer.from('%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF');

function step(title: string, body: () => Promise<void>, options: { timeout?: number } = {}) {
  test(title, async () => {
    if (options.timeout) test.setTimeout(options.timeout);
    test.skip(RESUME && Boolean(state.done[title]), 'шаг пройден в предыдущем запуске (E2E_RESUME=1)');
    await body();
    state.done[title] = true;
    save();
  });
}

/** Время последнего ответа 429 портала клиенту: лимит портала — 120 запросов в минуту на сессию, длинный сценарий (десятки экранов в минуту) его иногда достигает. */
let portalThrottledAt = 0;

/** Открывает экран клиента; если портал ответил 429 (лимит сессии), ждёт окно лимита и открывает снова — это не дефект экрана. */
async function open(path: string): Promise<void> {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const mark = Date.now();
    await client.goto(`${CABINET_URL}${path}`);
    await client.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => undefined);
    if (portalThrottledAt < mark) return;
    await client.waitForTimeout(20_000);
  }
}

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
  await expect(page.getByRole('heading', { name: 'Проверьте почту' })).toBeVisible();
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

/** Таблица на экране помещается в оболочку: ни одна видимая таблица не уходит в горизонтальную прокрутку своего контейнера (D-7 FIX-51: счета на 1440). */
async function expectTablesFit(page: Page, screen: string): Promise<void> {
  const clipped = await page.evaluate(() =>
    Array.from(document.querySelectorAll('table'))
      .filter((table) => table.getClientRects().length > 0)
      .filter((table) => {
        for (let el = table.parentElement; el && el !== document.documentElement; el = el.parentElement) {
          const { overflowX } = getComputedStyle(el);
          if ((overflowX === 'auto' || overflowX === 'scroll' || overflowX === 'hidden') && el.scrollWidth > el.clientWidth + 1) return true;
        }
        return false;
      }).length,
  );
  expect(clipped, `${screen}: таблица помещается без горизонтальной прокрутки`).toBe(0);
}

/** Печатные даты в интерфейсе: «ДД.ММ.ГГГГ», без «2026 M10 21» (D-4 FIX-51, uz). */
async function expectDatesLocalised(page: Page, screen: string): Promise<void> {
  await expect(page.locator('main'), `${screen}: есть дата ДД.ММ.ГГГГ`).toContainText(/\d{2}\.\d{2}\.\d{4}/);
  const text = await page.locator('main').innerText();
  expect(text, `${screen}: нет формата «2026 M10 21»`).not.toMatch(/(?<!\d)\d{4} M\d{1,2} \d{1,2}(?!\d)/);
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async ({ browser }) => {
  clientCtx = await browser.newContext({
    locale: 'ru-RU',
    viewport: { width: 1440, height: 900 },
    storageState: RESUME && fs.existsSync(CLIENT_STATE) ? CLIENT_STATE : undefined,
  });
  client = await clientCtx.newPage();
  client.on('response', (response) => {
    if (response.status() === 429 && response.url().includes('/api/portal/')) portalThrottledAt = Date.now();
  });
  const crmCtx = await browser.newContext({ locale: 'ru-RU', viewport: { width: 1440, height: 900 } });
  crm = await crmCtx.newPage();
  await crmLogin(crm);
  erp = await erpLoginFromCrm(crm);
  // Второй сотрудник: временный пароль (сброс из «Пользователи») живёт только в памяти процесса; дальше — тот же настоящий переход в ERP
  const managerCtx = await browser.newContext({ locale: 'ru-RU', viewport: { width: 1440, height: 900 } });
  const managerPage = await managerCtx.newPage();
  await crmLoginAs(managerPage, MANAGER_EMAIL, await resetStaffPassword(crm, 'FIX-51 Менеджер'));
  manager = await erpLoginFromCrm(managerPage);
  if (RESUME && state.done[A3]) {
    // продолжение прогона: сеанс клиента мог не сохраниться — тогда входим заново по ссылке из письма
    await client.goto(`${CABINET_URL}/requests`);
    await client.getByRole('heading', { level: 1 }).first().waitFor();
    if (/\/login/.test(client.url())) {
      await signInByForm(client, email);
    }
  }
});

test.afterAll(async () => {
  await clientCtx.storageState({ path: CLIENT_STATE });
});

test.describe('A. Вход и первое знакомство', () => {
  // D-1 (FIX-51, P1) исправлен в FIX-58: переход «В бэк-офис (ERP)» из CRM в чистом браузере раньше в 12 из 14 случаев
  // заканчивался формой входа ERP. Теперь — настоящий переход по кнопке в 10 новых контекстах подряд, без подмены страницы обмена.
  step(
    'A0. D-1: «В бэк-офис (ERP)» из CRM в чистом браузере — 10 из 10, без обхода',
    async () => {
      const browser = clientCtx.browser()!;
      const outcomes: SsoOutcome[] = [];
      for (let attempt = 1; attempt <= 10; attempt += 1) {
        let outcome: SsoOutcome = 'failed';
        for (let retry = 0; retry < 3; retry += 1) {
          const ctx = await browser.newContext({ locale: 'ru-RU', viewport: { width: 1440, height: 900 } });
          const page = await ctx.newPage();
          await crmLogin(page); // новый вход в CRM: cookie ERP в контексте нет, refresh-cookie CRM одноразовая — делить сессию между контекстами нельзя
          outcome = await clickThroughToErp(page);
          if (outcome === 'ok' && attempt === 1) await snap(page, 'sso-erp-from-crm', { blocking: false });
          await ctx.close();
          if (outcome !== 'throttled') break;
          await new Promise((resolve) => setTimeout(resolve, 65_000)); // лимит обмена 10/мин делят с соседней QA-задачей: ждём окно
        }
        outcomes.push(outcome);
        if (process.env.E2E_PROGRESS) fs.appendFileSync(process.env.E2E_PROGRESS, `D-1 попытка ${attempt}: ${outcome}\n`);
        await new Promise((resolve) => setTimeout(resolve, 7000)); // не больше ~8 обменов в минуту
      }
      state.sso = outcomes.map((o) => (o === 'ok' ? 'ok' : o)).join(',');
      console.log(`D-1: ${outcomes.filter((o) => o === 'ok').length} из 10 переходов дошли до ERP под сотрудником (${state.sso})`);
      expect(outcomes, 'каждый переход из чистого контекста открывает ERP под сотрудником').toEqual(Array(10).fill('ok'));
    },
    { timeout: 900_000 },
  );

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
    await page.getByLabel('Как к вам обращаться').fill('FIX-51b Клиент');
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
    await snap(crm, 'crm-lead-from-cabinet-form', { blocking: false });
    await takeAndHandOff(crm, state.leadId, COMPANY);
    await crm.goto(`${CRM_URL}/clients`);
    await snap(crm, 'crm-clients-after-handoff', { blocking: false });
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

test.describe('A+. CRM: лид, заведённый вручную (звонок), и согласие (D-8)', () => {
  // D-8 (FIX-51, P2) исправлен в FIX-57: у лида из звонка нет бота, где дать согласие, — менеджер отмечает «Согласие получено»
  // (способ, комментарий, аудит), после чего «Передать в бэк-офис» проходит.
  step('A4. D-8: ручной лид без согласия → «Согласие получено» → «Передать в бэк-офис»', async () => {
    await crm.goto(`${CRM_URL}/inbox`);
    await crm.getByRole('button', { name: 'Новый лид' }).click();
    const form = crm.getByRole('dialog');
    await form.getByLabel('Имя').fill(`FIX-51b Звонок ${state.tag}`);
    await form.getByLabel('Компания').fill(MANUAL_COMPANY);
    await form.getByLabel('Телефон').fill(manualPhone);
    await form.getByLabel('Что нужно').fill(`FIX-51b [${state.tag}] звонок: нужны рельсовые накладки, 20 шт`);
    await form.getByRole('button', { name: 'Создать' }).click();
    await expect(crm).toHaveURL(/\/leads\/\d+/);
    state.manualLeadId = Number(new URL(crm.url()).pathname.split('/').pop());
    save();
    // до: «Согласие: нет», главное действие — «Согласие получено»
    await expect(crm.getByText('нет', { exact: true }).first()).toBeVisible();
    await expect(crm.getByRole('group', { name: /Действия/ }).getByRole('button', { name: 'Согласие получено' })).toBeVisible();
    await snap(crm, 'crm-manual-lead-before-consent', { blocking: false });
    await leadAction(crm, 'Согласие получено');
    const dialog = crm.getByRole('dialog');
    await expect(dialog.getByText('Как получено согласие')).toBeVisible();
    await dialog.getByLabel('Комментарий (необязательно)').fill(`FIX-51b ${state.tag}: подтвердил по телефону`);
    await snap(crm, 'crm-consent-dialog', { blocking: false });
    await dialog.getByRole('button', { name: 'Согласие получено' }).click();
    await expect(crm.getByText('Согласие отмечено')).toBeVisible();
    // после: дата и способ в карточке, запись в журнале
    await expect(crm.getByText(/\d{2}\.\d{2}\.\d{4}, устно по телефону/)).toBeVisible();
    await snap(crm, 'crm-manual-lead-after-consent', { blocking: false });
    // передача проходит
    await leadAction(crm, 'Передать в бэк-офис');
    const handoff = crm.getByRole('dialog');
    await handoff.getByLabel('или новый клиент').fill(MANUAL_COMPANY);
    await handoff.getByRole('button', { name: 'Передать в бэк-офис' }).click();
    await expect(crm.getByText('Клиент создан')).toBeVisible();
    await expect(crm.getByText(/В бэк-офисе: Компания #\d+/)).toBeVisible();
    await snap(crm, 'crm-manual-lead-after-handoff', { blocking: false });
  });

  // FIX-31 (передача без потерь): состояния «Передаётся в бэк-офис» и «ИНН уже есть у другого клиента» на стенде — два клиента CRM
  // с одним ИНН и два лида: первый передаётся штатно и занимает ИНН в ERP, второй получает 409 INN_CONFLICT. Режим CRM ↔ ERP не меняется.
  step('A5. FIX-31: «Передаётся в бэк-офис» и «ИНН уже есть у другого клиента»', async () => {
    const inn = `35${String(Date.now()).slice(-7)}`;
    const names = [`FIX-51b ИНН-1 ${state.tag}`, `FIX-51b ИНН-2 ${state.tag}`];
    for (const name of names) await createClient(crm, name, inn);
    const phoneOf = (shift: number) => `+99895${String((Number.parseInt(state.tag.slice(1), 36) + shift) % 10_000_000).padStart(7, '0')}`;
    await createConsentedLead(crm, `FIX-51b ИНН-лид 1 ${state.tag}`, phoneOf(11), `FIX-51b [${state.tag}] проверка ИНН, первый`);
    await handoffToExistingClient(crm, names[0]!);
    await expect(crm.getByText('Передаётся в бэк-офис')).toBeVisible();
    await snap(crm, 'crm-handoff-pending', { blocking: false });
    await expect(crm.getByText(/В бэк-офисе: Компания #\d+/)).toBeVisible({ timeout: 90_000 });
    await createConsentedLead(crm, `FIX-51b ИНН-лид 2 ${state.tag}`, phoneOf(12), `FIX-51b [${state.tag}] проверка ИНН, второй`);
    await handoffToExistingClient(crm, names[1]!);
    await expect(crm.getByText('Передача в бэк-офис не удалась')).toBeVisible({ timeout: 90_000 });
    await expect(crm.getByText(/ИНН этого клиента уже есть в бэк-офисе у другого клиента CRM/)).toBeVisible();
    await snap(crm, 'crm-handoff-inn-conflict', { blocking: false });
  });
});

test.describe('B. Бэк-офис готовит КП (подготовка данных, не прогон M1)', () => {
  step('B1. сотрудник в ERP (вход из CRM по SSO): заявка → КП → согласование → отправка', async () => {
    state.dealA = await dealIdByNote(state.tag);
    const [bearing, belt, plate] = await pickProducts(erp, ['Накладка рельсовая', 'Шуруп путевой', 'Подкладка КБ-65']);
    state.quoteA = await buildAndSendQuote(manager, erp, state.dealA, [
      { product: bearing, quantity: 100, price: '150000.00' },
      { product: belt, quantity: 500, price: '8000.00' },
      { product: plate, quantity: 40, price: '25000.00' },
    ]);
    save();
    // D-11 (FIX-51, исправлен в FIX-55): шаги за других согласующих закрыл администратор — в журнале КП это помечено «от имени»
    const journal = await erp.ok('GET', 'crm/activity-logs/?page_size=100');
    const proxied = (journal.json.results as { detail: string; user_name: string; event_params: { on_behalf_of?: string } }[]).filter((entry) => entry.detail.includes('(от имени') && entry.user_name.includes('FIX-51'));
    expect(proxied.length, 'в журнале есть шаги согласования «от имени» (суперпользователь за другого согласующего)').toBeGreaterThan(0);
    expect(proxied[0]!.event_params.on_behalf_of, 'в параметрах события — за кого').toBeTruthy();
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
    // D-3 (FIX-51) не исправлен — вопрос архитектору Q-FIX55-1: ERP отдаёт `promised_date: null`, столбец «Срок» пуст. Не роняем прогон, фиксируем факт.
    const quoteRaw = await client.evaluate(async (id) => (await fetch(`/api/portal/v1/quotes/${id}`, { credentials: 'include' })).text(), new URL(client.url()).pathname.split('/').pop());
    const emptyDates = (quoteRaw.match(/"promised_date":\s*null/g) ?? []).length;
    const filledDates = (quoteRaw.match(/"promised_date":\s*"/g) ?? []).length;
    console.log(`D-3: promised_date пуст у ${emptyDates}, заполнен у ${filledDates}`);
    test.info().annotations.push({ type: 'D-3 не исправлен (Q-FIX55-1)', description: `promised_date: null — ${emptyDates}, заполнен — ${filledDates}` });
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
    // D-2 (FIX-51, исправлен в FIX-55): статус отгрузки до самой отгрузки (её создаёт Celery после подписи договора обеими
    // сторонами) — 409 с кодом, а не 500; мусорный deal_id — 404/400, а не 500.
    const early = await erp.call('POST', 'crm/fulfillments/update-status/', { deal_id: state.dealA, status: 'SHIPPED' });
    expect(early.status, `update-status до отгрузки: ${JSON.stringify(early.json)}`).toBe(409);
    expect(JSON.stringify(early.json)).toContain('FULFILLMENT_NOT_READY');
    const garbage = await erp.call('POST', 'crm/fulfillments/update-status/', { deal_id: 2_000_000_000, status: 'SHIPPED' });
    expect(garbage.status, `update-status с несуществующей сделкой: ${JSON.stringify(garbage.json)}`).toBeLessThan(500);
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
    await expectTablesFit(client, 'Счета, 1440');
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
    // D-7: «·» в шапке сделки виден на широком экране и не висит отдельной строкой на телефоне
    const visibleDots = () => client.evaluate(() => Array.from(document.querySelectorAll('h2 span')).filter((el) => el.textContent?.trim() === '·' && el.getClientRects().length > 0).length);
    expect(await visibleDots(), 'на 1440 разделитель «·» между номером и названием сделки есть').toBeGreaterThan(0);
    await client.setViewportSize({ width: 390, height: 844 });
    expect(await visibleDots(), 'на 390 разделителя «·» в шапке сделки нет').toBe(0);
    await client.setViewportSize({ width: 1440, height: 900 });
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
    await dialog.getByLabel('Причина замечания').fill('FIX-51b: маркировка на подкладках не соответствует накладной');
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
    await dialog.locator('input[type="file"]').setInputFiles({ name: 'FIX-51b-scan.pdf', mimeType: 'application/pdf', buffer: SCAN_PDF });
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
    // D-7: короткий плейсхолдер поиска целиком помещается в поле на 390 px
    const search = client.getByRole('searchbox', { name: 'Поиск документов' });
    await expect(search).toHaveAttribute('placeholder', 'Номер, название, сделка…');
    await client.setViewportSize({ width: 390, height: 844 });
    const placeholderFits = await search.evaluate((input: HTMLInputElement) => {
      const style = getComputedStyle(input);
      const ctx = document.createElement('canvas').getContext('2d')!;
      ctx.font = style.font;
      const room = input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return { text: ctx.measureText(input.placeholder).width, room };
    });
    expect(placeholderFits.text, `плейсхолдер (${Math.round(placeholderFits.text)} px) помещается в поле (${Math.round(placeholderFits.room)} px)`).toBeLessThanOrEqual(placeholderFits.room);
    await client.setViewportSize({ width: 1440, height: 900 });
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
    // C-9 (мелочь аудита): пустой результат поиска — «Ничего не найдено» и «Сбросить поиск», а не «документов пока нет»
    await search.fill('ZZZ-нет-такого-документа');
    await expect(client.getByText('Ничего не найдено')).toBeVisible();
    await snap(client, 'documents-search-empty');
    await client.getByRole('button', { name: 'Сбросить поиск' }).click();
    await expect(search).toHaveValue('');
    await expect(client.getByRole('row').filter({ hasText: 'Договор' }).first()).toBeVisible();
  });

  step('F2. D-6: накладная — итоговый номер сразу и не пустой файл; язык печати по получателю', async () => {
    type Doc = { id: number; kind: string; number: string; size_bytes?: number | null };
    const list = async (): Promise<Doc[]> =>
      client.evaluate(async () => {
        const body = await (await fetch('/api/portal/v1/documents', { credentials: 'include' })).json();
        return (Array.isArray(body) ? body : (body.results ?? body.items ?? [])) as Doc[];
      });
    const waybill = (await list()).find((doc) => doc.kind === 'waybill');
    expect(waybill, 'в «Документах» есть накладная по доставленной сделке').toBeTruthy();
    expect(waybill!.number, 'накладная сразу с итоговым номером, не черновым «DN-<id>»').toMatch(/^DN-\d{4}-\d+$/);
    // скачивание: рендер может занять время (202 + Retry-After) — ждём файл; номер при этом не меняется
    let status = 0;
    for (let attempt = 0; attempt < 30 && status !== 200; attempt += 1) {
      status = await client.evaluate(async (id) => (await fetch(`/api/portal/v1/documents/${id}/file`, { credentials: 'include' })).status, waybill!.id);
      if (status === 202) await client.waitForTimeout(2000);
    }
    expect(status, 'накладная скачивается (PDF готов)').toBe(200);
    const after = (await list()).find((doc) => doc.id === waybill!.id)!;
    expect(after.number, 'номер накладной не меняется после рендера').toBe(waybill!.number);
    if (after.size_bytes !== undefined && after.size_bytes !== null) expect(after.size_bytes, 'размер накладной после рендера не нулевой').toBeGreaterThan(0);
    // «Could not resolve recipient language for delivery_note» (воркер) — не должно быть за время прогона
    expect(logLines('erp-worker', 'Could not resolve recipient language', RUN_START), 'в логе воркера нет ошибки языка получателя').toEqual([]);
    await open('/documents');
    await expect(client.getByRole('row').filter({ hasText: waybill!.number }).first()).toBeVisible();
    await snap(client, 'documents-waybill');
  });
});

test.describe('G. Новый запрос из каталога → отказ от КП → возврат акта', () => {
  // FIX-54 (P-18): картинки каталога — абсолютные ссылки на домен Cabinet, Caddy ведёт /media/* на ERP. У позиций стенда фото нет,
  // поэтому подготовка данных — прикрепить синтетическое фото к опубликованной позиции «Железный шпала» (в конце прогона убирается).
  step('G0. картинки каталога идут через /media на домене Cabinet и открываются', async () => {
    const [sleeper] = await pickProducts(erp, ['Железный шпала']);
    state.photoProduct = sleeper;
    const uploaded = await erp.upload(`catalog/products/${sleeper}/upload-image/`, 'image', { name: 'fix51b-sleeper.png', mimeType: 'image/png', buffer: sleeperPng() });
    expect(uploaded.status, `фото товара: ${JSON.stringify(uploaded.json).slice(0, 200)}`).toBeLessThan(300);
    state.photoId = (uploaded.json as { id?: number } | null)?.id;
    save();
    await open('/catalog');
    const itemId = await client.evaluate(async () => {
      const body = await (await fetch('/api/portal/v1/catalog?page_size=100', { credentials: 'include' })).json();
      const items = (Array.isArray(body) ? body : (body.results ?? body.items ?? [])) as { id: number; name: string }[];
      return items.find((item) => item.name.includes('Железный шпала'))?.id ?? null;
    });
    expect(itemId, 'позиция «Железный шпала» есть в каталоге Cabinet').not.toBeNull();
    const detail = await client.evaluate(async (id) => (await (await fetch(`/api/portal/v1/catalog/${id}`, { credentials: 'include' })).json()) as { images?: string[] }, itemId);
    expect(detail.images?.length, 'портал отдаёт ссылки на фото').toBeGreaterThan(0);
    const image = new URL(detail.images![0]!);
    expect(image.host, 'ссылка на фото — на домене Cabinet (через /media), не на ERP').toBe(new URL(CABINET_URL).host);
    expect(image.pathname).toMatch(/^\/media\/products\/\d+\/images\//);
    const media = client.waitForResponse((response) => response.url().includes('/media/products/'));
    await open(`/catalog/${itemId}`);
    expect((await media).status(), 'фото отдаётся').toBe(200);
    const photo = client.getByRole('img', { name: /Железный шпала/ }).first();
    await expect(photo).toBeVisible();
    await expect.poll(() => photo.evaluate((img: HTMLImageElement) => (img.complete ? img.naturalWidth : 0))).toBeGreaterThan(0);
    await expect(client.getByText('В наличии').first()).toBeVisible();
    expect(await client.locator('main').innerText(), 'у позиции «В наличии» нет «срок 0 дней»').not.toMatch(/срок\s*:?\s*0\s/i);
    await snap(client, 'catalog-item-with-photo');
  });

  step('G1. каталог → «В запрос» → запрос', async () => {
    await open('/catalog');
    await expect(client.getByRole('button', { name: 'В запрос' }).first()).toBeVisible();
    // D-5 (FIX-51, исправлен в FIX-56): «В наличии» без «срок 0 дней»
    await expect(client.getByText('В наличии').first()).toBeVisible();
    expect(await client.locator('main').innerText(), 'у позиций «В наличии» нет «срок 0 дней»').not.toMatch(/срок\s*:?\s*0\s/i);
    await snap(client, 'catalog');
    await client.getByRole('button', { name: 'В запрос' }).first().click();
    await client.getByRole('button', { name: /^Оформить запрос/ }).click();
    await expect(client).toHaveURL(/\/requests\/new/);
    // C-9 (FIX-51, исправлен в FIX-56): черновик «Нового запроса» переживает уход со страницы (sessionStorage вкладки)
    const draftText = `FIX-51b [${state.tag}] запрос из каталога: 50 шт, доставка на станцию Навои`;
    await client.getByLabel('Что нужно').fill(draftText);
    await client.getByLabel(/^Строка 1/).fill('FIX-51b: болт М20 в черновике');
    await client.getByLabel('Количество').first().fill('50');
    await client.waitForTimeout(500);
    await open('/requests');
    await expect(client.getByRole('heading', { level: 1, name: 'Запросы' })).toBeVisible();
    await open('/requests/new');
    await expect(client.getByLabel('Что нужно')).toHaveValue(draftText);
    await expect(client.getByLabel(/^Строка 1/)).toHaveValue('FIX-51b: болт М20 в черновике');
    await expect(client.getByLabel('Количество').first()).toHaveValue('50');
    await snap(client, 'request-new-draft-restored');
    await snap(client, 'request-new-from-catalog');
    await client.getByRole('button', { name: 'Отправить запрос' }).click();
    await expect(client).toHaveURL(/\/requests\/\d+$/);
    await expect(client.getByText(/Запрос Z-\d+ отправлен/)).toBeVisible();
    // после отправки черновика нет
    expect(await client.evaluate(() => Object.keys(window.sessionStorage).filter((key) => key.includes('requestDraft'))), 'после отправки черновик стёрт').toEqual([]);
    await snap(client, 'request-detail-new');
  });

  step('G2. бэк-офис отправляет КП v1; клиент отклоняет с причиной', async () => {
    state.dealB = await dealIdByNote(`запрос из каталога: 50 шт`);
    const [item] = await pickProducts(erp, ['Железный шпала']);
    state.quoteB = await buildAndSendQuote(manager, erp, state.dealB, [{ product: item, quantity: 50, price: '90000.00' }]);
    save();
    await open('/quotes');
    await client.getByRole('link', { name: /версия 1/ }).first().click();
    await client.getByRole('button', { name: 'Отклонить' }).click();
    const dialog = client.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Отклонить КП' }).click(); // без причины — нельзя
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Причина').fill('FIX-51b: срок поставки не устраивает, нужен 10 дней');
    await snap(client, 'quote-reject-dialog');
    await dialog.getByRole('button', { name: 'Отклонить КП' }).click();
    await expect(client.getByText('КП отклонено').first()).toBeVisible();
    await snap(client, 'quote-rejected');
  });

  step('G3. новая версия КП → принять → договор → счёт → акт → клиент возвращает акт', async () => {
    const v2 = await resendQuoteVersion(manager, erp, state.quoteB!);
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
    await returnDialog.getByLabel('Причина возврата').fill('FIX-51b: не указан серийный номер партии');
    await snap(client, 'act-return-dialog');
    await returnDialog.getByRole('button', { name: 'Вернуть акт' }).click();
    await expect(client.getByText(/Возвращён: FIX-51b/)).toBeVisible();
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
    await dialog.getByLabel('Имя и фамилия').fill('FIX-51b Наблюдатель');
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
      if (code === 'uz') {
        // D-4 (FIX-51, исправлен в FIX-56): даты в узбекском интерфейсе — «ДД.ММ.ГГГГ», а не «2026 M10 21»
        await expectDatesLocalised(client, 'Soʻrovlar (uz)');
        await open('/invoices');
        await expect(client.getByRole('heading', { level: 1 })).toBeVisible();
        await expectDatesLocalised(client, 'Hisoblar (uz)');
        await expectTablesFit(client, 'Hisoblar (uz), 1440');
        await snap(client, 'invoices-uz');
        await open('/documents');
        await client.getByRole('searchbox').fill('ZZZ-yoq');
        await snap(client, 'documents-search-empty-uz');
      }
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
    const denied = await viewer.evaluate(async (quoteId) => (await fetch(`/api/portal/v1/quotes/${quoteId}/reject`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ reason: 'FIX-51b проверка прав' }) })).status, state.quoteB!);
    expect([403, 409]).toContain(denied);
    await ctx.close();
  });

  step('I2. изоляция: чужие объекты — 404, в ответах нет себестоимости, маржи и поставщиков', async () => {
    const { json } = await erp.ok('GET', 'crm/quotes/?page_size=100');
    const foreign = (json.results as { id: number; deal: number }[]).find((q) => q.id !== state.quoteA && q.id !== state.quoteB && q.deal !== state.dealA && q.deal !== state.dealB);
    expect(foreign, 'в ERP есть КП другой компании').toBeTruthy();
    await open('/requests');
    // портальный лимит запросов (P-14) мог сработать после длинного прогона: при 429 ждём Retry-After и повторяем
    const result = await client.evaluate(async (foreignQuote) => {
      const get = async (url: string): Promise<{ status: number; text: string }> => {
        for (let attempt = 0; ; attempt += 1) {
          const response = await fetch(`/api/portal/v1${url}`, { credentials: 'include' });
          if (response.status !== 429 || attempt >= 4) return { status: response.status, text: await response.text() };
          await new Promise((resolve) => setTimeout(resolve, (Number(response.headers.get('Retry-After')) || 15) * 1000));
        }
      };
      const own: (readonly [string, { status: number; text: string }])[] = [];
      for (const url of ['/quotes', '/contracts', '/invoices', '/acts', '/deliveries', '/documents', '/requests', '/catalog', '/company', '/team', '/me']) own.push([url, await get(url)] as const);
      return { foreign: await get(`/quotes/${foreignQuote}`), own };
    }, foreign!.id);
    expect(result.foreign.status, 'чужое КП недоступно').toBe(404);
    const leak = /margin|markup|landed|cost|supplier|purchase|закупк|себестоим|поставщик/i;
    for (const [url, response] of result.own) {
      expect(response.status, `GET ${url}`).toBe(200);
      expect(response.text, `в ответе ${url} нет внутренних полей`).not.toMatch(leak);
    }
    // FIX-54 (хвост FIX-25): неизвестный путь портала — JSON 404, а не HTML-страница
    const unknown = await client.evaluate(async () => {
      const response = await fetch('/api/portal/v1/net-takogo-puti', { credentials: 'include' });
      return { status: response.status, type: response.headers.get('content-type') ?? '', body: await response.text() };
    });
    expect(unknown.status, 'неизвестный путь портала').toBe(404);
    expect(unknown.type, 'ответ — JSON').toContain('application/json');
    expect(() => JSON.parse(unknown.body), 'тело — валидный JSON').not.toThrow();
  });

  step('I3. выход и повторный вход по ссылке из письма; использованная ссылка', async () => {
    await open('/profile');
    await client.getByRole('button', { name: 'Выйти из кабинета' }).click();
    await expect(client).toHaveURL(/\/login/);
    const known = magicTokens(email);
    await client.getByLabel('E-mail').fill(email);
    await client.getByRole('button', { name: 'Войти' }).click();
    await expect(client.getByRole('heading', { name: 'Проверьте почту' })).toBeVisible();
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
    // D-10 (FIX-51, исправлен в FIX-57): карточка лида показывает заявку, созданную передачей, а не позднейшую заявку клиента из Cabinet
    await expect(crm.getByText(`Заявка #${state.dealA}`)).toBeVisible();
    await expect(crm.getByText(`Заявка #${state.dealB}`)).toHaveCount(0);
    await snap(crm, 'crm-lead-after-handoff', { blocking: false });
    await crm.getByRole('link', { name: 'Открыть карточку клиента' }).click();
    await expect(crm.getByRole('heading', { level: 1, name: COMPANY })).toBeVisible();
    await expect(crm.getByRole('row', { name: /В бэк-офисе.*Компания #\d+/ })).toBeVisible();
    await snap(crm, 'crm-client-card', { blocking: false });
    await crm.getByRole('tab', { name: /^Сделки/ }).click();
    await expect(crm.getByText('Выиграна').first()).toBeVisible();
    // D-9 (FIX-51, исправлен в FIX-57): на 390 px сумма сделки не рвётся посреди числа
    await crm.setViewportSize({ width: 390, height: 844 });
    const wrapped = await crm.evaluate(() => {
      const broken: string[] = [];
      for (const cell of Array.from(document.querySelectorAll('td'))) {
        const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          if (!/\d\s?\d{3}.*UZS|UZS|USD/.test(node.textContent ?? '')) continue;
          const range = document.createRange();
          range.selectNodeContents(node);
          const lines = new Set(Array.from(range.getClientRects()).map((r) => Math.round(r.top)));
          if (lines.size > 1) broken.push(node.textContent!.trim());
        }
      }
      return broken;
    });
    await crm.setViewportSize({ width: 1440, height: 900 });
    expect(wrapped, 'суммы сделок на 390 px в одну строку').toEqual([]);
    await snap(crm, 'crm-client-deals', { blocking: false });
    await crm.getByRole('tab', { name: /^Документы/ }).click();
    await expect(crm.getByRole('row').filter({ hasText: 'Акт' }).first()).toBeVisible();
    await snap(crm, 'crm-client-documents', { blocking: false });
  });

  step('J2. «Сделки» CRM: стадии пришли событиями ERP (FIX-30, FIX-33)', async () => {
    await open('/deals');
    await expect(crm.getByRole('row').filter({ hasText: 'FIX-51b' }).first()).toBeVisible();
    await snap(crm, 'crm-deals', { blocking: false });
    // I-26 (FIX-57): у зеркальной сделки ERP поля ERP только чтение — «Ведётся в бэк-офисе (ERP)»
    const mirror = crm.getByRole('row').filter({ hasText: `#${state.dealA}` }).first();
    await expect(mirror).toBeVisible();
    await mirror.getByRole('button', { name: /Действия|Меню|Ещё|действия/i }).first().click();
    await crm.getByRole('menuitem', { name: 'Изменить' }).click();
    const deal = crm.getByRole('dialog');
    await expect(deal.getByText('Ведётся в бэк-офисе (ERP)').first()).toBeVisible();
    await expect(deal.getByLabel('Название')).toHaveCount(0);
    await snap(crm, 'crm-deal-erp-owned', { blocking: false });
    await deal.getByRole('button', { name: 'Отмена' }).click();
  });

  step('J3. «Внешние сервисы»: «События из ERP», «Передача клиентов в ERP» (FIX-33)', async () => {
    await open('/external-services');
    await expect(crm.getByRole('link', { name: 'События из ERP' })).toBeVisible();
    await snap(crm, 'crm-external-services', { blocking: false });
    await crm.getByRole('link', { name: 'События из ERP' }).click();
    await expect(crm.getByRole('heading', { name: 'События из ERP' }).first()).toBeVisible();
    await snap(crm, 'crm-external-services-erp-events', { blocking: false });
  });

  step('J4. «Подключения → ERP»: секреты не на экране, ротация секрета (FIX-35)', async () => {
    await open('/integrations');
    await crm.getByRole('tab', { name: 'ERP' }).click();
    await expect(crm.getByLabel('Предыдущий секрет вебхуков')).toBeVisible();
    // секреты — только «····1234»: ни одно поле формы не несёт значения, длинных токенов на экране нет
    const values = await crm.locator('input').evaluateAll((nodes) => nodes.map((n) => (n as HTMLInputElement).value));
    expect(values.filter((v) => v.length > 40), 'в полях формы нет длинных секретов').toEqual([]);
    expect(await crm.locator('main').innerText()).not.toMatch(/[A-Za-z0-9_-]{40,}/);
    await snap(crm, 'crm-integrations-erp', { blocking: false });
  });

  step('J5. «Настройки»: адрес кабинета и тексты бота по событиям ERP (FIX-34)', async () => {
    await open('/settings');
    await expect(crm.getByText('Адрес кабинета клиента').first()).toBeVisible();
    await snap(crm, 'crm-settings-company', { blocking: false });
    await crm.getByText('Тексты бота', { exact: true }).click();
    await expect(crm.getByText(/События бэк-офиса \(ERP\)/).first()).toBeVisible();
    await snap(crm, 'crm-settings-bot-texts', { blocking: false });
  });
});

test.describe('K. Уборка за прогоном', () => {
  step('K1. фото, прикреплённое к позиции каталога для проверки, убрано', async () => {
    if (!state.photoProduct || !state.photoId) return;
    const removed = await erp.call('DELETE', `catalog/products/${state.photoProduct}/delete-image/${state.photoId}/`);
    expect([204, 404], `удаление фото FIX-51b: ${removed.status}`).toContain(removed.status);
  });
});
