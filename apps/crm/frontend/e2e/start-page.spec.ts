import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

// W11B-G-3 и W11B-G-5 (волна 11c, F2): стартовая страница — первый доступный раздел по правам;
// без права `stream:read` клиент не открывает поток и не показывает «Нет связи».
// Системный «Администратор» (R3-D-2) прав на лиды, клиентов, дашборд и поток не имеет, поэтому
// сценарий идёт под НОВЫМ сотрудником только с этой ролью: общий admin@demo.local другие сценарии
// (admin.spec.ts) наделяют второй ролью «Менеджер».
const adminEmail = process.env["E2E_ADMIN_EMAIL"] ?? "admin@demo.local";
const adminPassword = process.env["E2E_ADMIN_PASSWORD"] ?? "";
const managerEmail = process.env["E2E_MANAGER_EMAIL"] ?? "manager@demo.local";
const managerPassword = process.env["E2E_MANAGER_PASSWORD"] ?? "";
// Только для этого сценария; в репозитории это не секрет, а пароль одноразового сотрудника e2e-базы.
const pureAdminPassword = "E2e-Pure-Admin-2026";

interface PlatformRole {
  id: number;
  code: string | null;
}

async function token(request: APIRequestContext, email: string, password: string) {
  const auth = await request.post("/api/v1/auth/login", { data: { email, password } });
  expect(auth.ok(), await auth.text()).toBeTruthy();
  return ((await auth.json()) as { access_token: string }).access_token;
}

/** Сотрудник только с системной ролью «Администратор»: временный пароль сменён, вход обычный. */
async function createPureAdmin(request: APIRequestContext): Promise<string> {
  const headers = { Authorization: `Bearer ${await token(request, adminEmail, adminPassword)}` };
  const roles = (await (
    await request.get("/api/v1/platform-roles", { headers })
  ).json()) as PlatformRole[];
  const adminRole = roles.find((role) => role.code === "ADMIN");
  expect(adminRole, "системная роль «Администратор»").toBeDefined();
  const email = `pure-admin-${String(Date.now())}-${String(Math.floor(Math.random() * 1e6))}@demo.local`;
  const created = await request.post("/api/v1/users", {
    headers,
    data: { email, full_name: "Админ Без Лидов", platform_role_ids: [adminRole?.id] },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const temporary = ((await created.json()) as { temporary_password: string }).temporary_password;
  const own = { Authorization: `Bearer ${await token(request, email, temporary)}` };
  const changed = await request.post("/api/v1/auth/change-password", {
    headers: own,
    data: { current_password: temporary, new_password: pureAdminPassword },
  });
  expect(changed.ok(), await changed.text()).toBeTruthy();
  return email;
}

/** Снимки для PR: десктоп — 1440 px (мобильный проект уже 390 px). */
async function desktopWidth(page: Page) {
  if (test.info().project.name === "chromium")
    await page.setViewportSize({ width: 1440, height: 900 });
}

function watchStream(page: Page): string[] {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/stream") requests.push(request.url());
  });
  return requests;
}

async function fillLogin(page: Page, email: string, password: string) {
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Войти" }).click();
}

test("admin without lead rights: first available section, no stream, no «Нет связи»", async ({
  page,
  request,
}) => {
  test.skip(!adminPassword, "E2E_ADMIN_PASSWORD не задан");
  const email = await createPureAdmin(request);
  const stream = watchStream(page);
  await desktopWidth(page);

  await page.goto("/");
  await page.waitForURL(/\/login/);
  await fillLogin(page, email, pureAdminPassword);

  // Не «/leads» с «Нет доступа», а доступный раздел администратора.
  await page.waitForURL(/\/users$/);
  await expect(page.getByRole("heading", { name: "Пользователи", level: 1 })).toBeVisible();
  await expect(page.getByText("Нет доступа к этому разделу")).toHaveCount(0);
  // Шапка прогрузилась (здоровье системы или пусто), но «Нет связи» нет, поток не открывался.
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("Нет связи")).toHaveCount(0);
  await page.waitForTimeout(3500); // дольше прежнего интервала повтора (3 с)
  expect(stream, "запросы к /api/v1/stream без права").toEqual([]);

  const project = test.info().project.name;
  await page.screenshot({
    path: `test-results/start-admin-${project}.png`,
    fullPage: true,
  });
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(axe.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

  // Явный «/» ведёт туда же, а не на «/leads».
  await page.goto("/");
  await page.waitForURL(/\/users$/);
});

test("admin without lead rights: deep link survives login", async ({ page, request }) => {
  test.skip(!adminPassword, "E2E_ADMIN_PASSWORD не задан");
  const email = await createPureAdmin(request);
  await page.goto("/integrations?tab=erp");
  await page.waitForURL(/\/login\?to=/);
  await fillLogin(page, email, pureAdminPassword);
  await page.waitForURL(/\/integrations\?tab=erp$/);
  await expect(page.getByRole("heading", { name: "Подключения" })).toBeVisible();
});

test("manager: inbox as before, stream opened, status shown", async ({ page }) => {
  test.skip(!managerPassword, "E2E_MANAGER_PASSWORD не задан");
  const stream = watchStream(page);
  await desktopWidth(page);
  await page.goto("/");
  await page.waitForURL(/\/login/);
  await fillLogin(page, managerEmail, managerPassword);
  await page.waitForURL(/\/inbox/);
  await expect(page.getByRole("heading", { name: "Входящие", level: 1 })).toBeVisible();
  await expect.poll(() => stream.length).toBeGreaterThan(0);
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: /Онлайн|Нет связи/ })
      .first(),
  ).toBeAttached();
  await page.screenshot({
    path: `test-results/start-manager-${test.info().project.name}.png`,
    fullPage: true,
  });
});
