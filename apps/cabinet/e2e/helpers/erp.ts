import { expect, type APIRequestContext, type Page } from '@playwright/test';
import { CRM_URL, ERP_URL } from './env';

export interface ErpResult<T = any> { // eslint-disable-line @typescript-eslint/no-explicit-any -- ответы ERP разбираются точечно
  status: number;
  json: T;
}

/** Клиент API бэк-офиса ERP под сессией сотрудника FIX-51 (то же, что делает ERP SPA, без кликов по его интерфейсу). */
export class ErpApi {
  constructor(
    private readonly request: APIRequestContext,
    private readonly token: string,
  ) {}

  async call(method: 'GET' | 'POST' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<ErpResult> {
    const response = await this.request.fetch(`${ERP_URL}/api/v1/${path}`, {
      method,
      headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' },
      data: body === undefined ? undefined : JSON.stringify(body),
    });
    const json = await response.json().catch(() => null);
    return { status: response.status(), json };
  }

  /** Загрузка файла (multipart), например фото товара. */
  async upload(path: string, field: string, file: { name: string; mimeType: string; buffer: Buffer }): Promise<ErpResult> {
    const response = await this.request.fetch(`${ERP_URL}/api/v1/${path}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.token}` },
      multipart: { [field]: file, alt_text: 'FIX-51b: проверка картинок каталога' },
    });
    return { status: response.status(), json: await response.json().catch(() => null) };
  }

  /** Вызов, который обязан пройти: иначе подготовка данных прогона сломана — падаем с кодом ответа. */
  async ok(method: 'GET' | 'POST' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<ErpResult> {
    const result = await this.call(method, path, body);
    expect(result.status, `${method} ${path} → ${JSON.stringify(result.json).slice(0, 200)}`).toBeLessThan(300);
    return result;
  }
}

export type SsoOutcome = 'ok' | 'throttled' | 'failed';

/**
 * Настоящий переход сотрудника «В бэк-офис (ERP)» из CRM (D-1 FIX-51, исправлен в FIX-58): кнопка в шапке CRM → одноразовый
 * SSO-токен во фрагменте → страница `/sso/exchange` ERP SPA обменивает его на сессию → дашборд ERP. Без обходов:
 * страницу обмена не подменяем, запрос обмена не делаем сами. Токен — только в адресной строке браузера.
 * `throttled` — обмен или refresh упёрся в 429 (лимиты стенда делят с соседней QA-задачей) — это не дефект перехода, попытку повторяют.
 */
export async function clickThroughToErp(page: Page): Promise<SsoOutcome> {
  const throttled: string[] = [];
  page.on('response', (response) => {
    // 429 на обмене (10/мин) или на refresh (общий анонимный лимит 20/мин на IP стенда): лимиты делят с соседней QA-задачей
    if (response.status() === 429 && response.url().includes('/api/v1/auth/')) throttled.push(new URL(response.url()).pathname);
  });
  await page.goto(`${CRM_URL}/inbox`);
  await page.getByText('В бэк-офис (ERP)').click();
  await page.waitForURL(`${ERP_URL}/**`);
  const until = Date.now() + 25_000;
  while (Date.now() < until) {
    if (await page.getByText('Дашборд', { exact: true }).first().isVisible().catch(() => false)) return 'ok';
    if (throttled.length) return 'throttled';
    await page.waitForTimeout(400);
  }
  if (throttled.length) return 'throttled';
  console.log(`переход в ERP не удался без 429: адрес ${new URL(page.url()).pathname}, заголовок «${(await page.locator('h1, h2').first().innerText().catch(() => '')).slice(0, 60)}»`);
  return 'failed';
}

/**
 * Сессия сотрудника в ERP для подготовки данных: после настоящего перехода из CRM (`clickThroughToErp`) токен доступа берётся
 * из refresh-cookie, которую выдал обмен (так же делает ERP SPA при загрузке), — ERP SPA хранит access только в памяти страницы.
 */
export async function erpLoginFromCrm(crmPage: Page): Promise<ErpApi> {
  for (let attempt = 1; ; attempt += 1) {
    const outcome = await clickThroughToErp(crmPage);
    if (outcome === 'ok') break;
    expect(outcome === 'throttled' && attempt < 3, `переход «В бэк-офис (ERP)» из CRM: ${outcome}, попытка ${attempt}`).toBe(true);
    await crmPage.waitForTimeout(65_000); // окно лимита обмена
  }
  const refreshed = await crmPage.evaluate(async () => {
    const response = await fetch('/api/v1/auth/token/refresh/', { method: 'POST', credentials: 'include' });
    return { status: response.status, body: (await response.json().catch(() => null)) as { access?: string } | null };
  });
  expect(refreshed.status, 'токен доступа ERP из cookie сессии, выданной SSO').toBe(200);
  return new ErpApi(crmPage.context().request, refreshed.body!.access!);
}
