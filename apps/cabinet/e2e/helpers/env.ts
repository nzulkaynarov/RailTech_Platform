import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** Адреса и переменные окружения прогона. Пароли и токены — только отсюда, в коде их нет. */
const here = path.dirname(fileURLToPath(import.meta.url));

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Задайте переменную окружения ${name} (см. шапку e2e/gate-m2.spec.ts)`);
  return value;
}

export const CABINET_URL = (process.env.E2E_BASE_URL ?? 'http://cabinet.localhost:8088').replace(/\/$/, '');
export const CRM_URL = (process.env.E2E_CRM_URL ?? CABINET_URL.replace('//cabinet.', '//crm.')).replace(/\/$/, '');
export const ERP_URL = (process.env.E2E_ERP_URL ?? CABINET_URL.replace('//cabinet.', '//erp.')).replace(/\/$/, '');

export const crmAdmin = () => ({
  email: required('E2E_CRM_ADMIN_EMAIL'),
  password: required('E2E_CRM_ADMIN_PASSWORD'),
});

/** Корень репозитория со стендом и `.env`: оттуда `docker compose logs` читает письма (почта стенда — консоль). */
export const standRoot = () => required('E2E_STAND_ROOT');

/** Куда класть скриншоты и сводку axe (в репозитории — docs/screens/fix-51). */
export const SCREENS_DIR = path.resolve(here, process.env.E2E_SCREENS_DIR ?? '../../../../docs/screens/fix-51');

/** Файл состояния прогона (метка, id в ERP, сессия клиента) — для `E2E_RESUME=1`; лежит в node_modules/.cache (Playwright чистит test-results при каждом запуске), в репозиторий не попадает. */
export const STATE_FILE = path.resolve(here, '../../node_modules/.cache/gate-m2/state.json');
export const RESUME = process.env.E2E_RESUME === '1';
