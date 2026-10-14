import { http, HttpResponse } from 'msw';

import { apiErrorKey } from '@/api/errors';
import { PortalApiError, getMe, requestMagicLink } from '@/api/portal';
import { portalServer } from '@/mocks/server';
import { signedIn } from '@/test/render';

describe('клиент портального API', () => {
  it('ходит в /api/portal/v1 с cookie (credentials: include) и Idempotency-Key на POST', async () => {
    const seen: Request[] = [];
    portalServer.events.on('request:start', ({ request }) => void seen.push(request.clone()));
    signedIn();
    await getMe();
    await requestMagicLink('a@b.uz');
    portalServer.events.removeAllListeners();

    expect(new URL(seen[0].url).pathname).toBe('/api/portal/v1/me');
    expect(seen[0].credentials).toBe('include');
    expect(seen[0].headers.get('Idempotency-Key')).toBeNull();
    expect(seen[1].method).toBe('POST');
    expect(seen[1].headers.get('Idempotency-Key')).toMatch(/.{8,}/);
  });

  it('ошибка {"detail": CODE} → PortalApiError и ключ apiErrors.<CODE>', async () => {
    portalServer.use(http.get('*/api/portal/v1/me', () => HttpResponse.json({ detail: 'CONTACT_NOT_FOUND' }, { status: 401 })));
    const error = await getMe().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PortalApiError);
    expect(error).toMatchObject({ status: 401, code: 'CONTACT_NOT_FOUND' });
    expect(apiErrorKey(error)).toBe('apiErrors.CONTACT_NOT_FOUND');
  });

  it('неизвестный код → текст по статусу; 404 всегда «не найдено»; сеть → NETWORK', async () => {
    expect(apiErrorKey(new PortalApiError(403, 'SOMETHING_NEW'))).toBe('apiErrors.FORBIDDEN');
    expect(apiErrorKey(new PortalApiError(404, 'QUOTE_FINALIZED'))).toBe('apiErrors.NOT_FOUND');
    expect(apiErrorKey(new PortalApiError(500, 'HTTP_500'))).toBe('apiErrors.UNKNOWN');
    portalServer.use(http.get('*/api/portal/v1/me', () => HttpResponse.error()));
    const error = await getMe().catch((e: unknown) => e);
    expect(apiErrorKey(error)).toBe('apiErrors.NETWORK');
  });
});
