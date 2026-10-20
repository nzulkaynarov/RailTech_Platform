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

  async call(method: 'GET' | 'POST' | 'PATCH', path: string, body?: unknown): Promise<ErpResult> {
    const response = await this.request.fetch(`${ERP_URL}/api/v1/${path}`, {
      method,
      headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' },
      data: body === undefined ? undefined : JSON.stringify(body),
    });
    const json = await response.json().catch(() => null);
    return { status: response.status(), json };
  }

  /** Вызов, который обязан пройти: иначе подготовка данных прогона сломана — падаем с кодом ответа. */
  async ok(method: 'GET' | 'POST' | 'PATCH', path: string, body?: unknown): Promise<ErpResult> {
    const result = await this.call(method, path, body);
    expect(result.status, `${method} ${path} → ${JSON.stringify(result.json).slice(0, 200)}`).toBeLessThan(300);
    return result;
  }
}

/**
 * Вход в ERP из CRM, как у сотрудника: кнопка «В бэк-офис (ERP)» → одноразовый SSO-токен → обмен на сессию.
 * Страницу `/sso/exchange` ERP SPA здесь не открываем: на стенде она в 7 из 8 случаев сбрасывает вход (дефект,
 * см. отчёт), поэтому обмен делает сам сценарий тем же запросом `POST /api/v1/auth/sso/exchange/`. Токен — только в памяти.
 */
export async function erpLoginFromCrm(crmPage: Page): Promise<ErpApi> {
  await crmPage.route(`${ERP_URL}/sso/exchange*`, (route) => route.fulfill({ contentType: 'text/html', body: '<html><body>sso</body></html>' }));
  await crmPage.goto(`${CRM_URL}/inbox`);
  await crmPage.getByText('В бэк-офис (ERP)').click();
  await crmPage.waitForURL(`${ERP_URL}/**`);
  const exchanged = await crmPage.evaluate(async () => {
    const token = new URLSearchParams(location.hash.slice(1)).get('token');
    const response = await fetch('/api/v1/auth/sso/exchange/', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    return { status: response.status, body: (await response.json().catch(() => null)) as { access_token?: string } | null };
  });
  await crmPage.unroute(`${ERP_URL}/sso/exchange*`);
  expect(exchanged.status, 'обмен SSO-токена на сессию ERP').toBe(200);
  return new ErpApi(crmPage.context().request, exchanged.body!.access_token!);
}
