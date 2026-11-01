import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, railLinks, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption, pickFiles } from "./support/fields";
import { PILOT_ROLES, ROLE_NAMES, type Role, visibleModules } from "./support/rbac";

// P8 «Роли пилота и регистрация входящих» на MSW (SPEC-v3 §3.2a п. 1, §4.1): меню четырёх ролей пилота; делопроизводитель
// регистрирует требование ГНК («срочно» само), видит предупреждение о дубле и не может наложить резолюцию; директор видит ВХ
// «Ждёт резолюции» в «Моих задачах» и форму резолюции; менеджер-универсал — расчёт, проекты, счета и оплаты. Обе ширины, axe.
const WIDTHS = [1440, 390] as const;
const EMAIL: Record<Role, string> = {
  ADMIN: "admin@demo.example",
  DIRECTOR: "director@demo.example",
  REGISTRAR: "registrar@demo.example",
  MANAGER_ALL: "universal@demo.example",
  MANAGER: "manager@demo.example",
  SUPPLY: "supply@demo.example",
  ENGINEER: "engineer@demo.example",
  ACCOUNTANT: "accountant@demo.example",
};
const SLUG: Record<Role, string> = {
  ADMIN: "admin",
  DIRECTOR: "director",
  REGISTRAR: "registrar",
  MANAGER_ALL: "manager-all",
  MANAGER: "manager",
  SUPPLY: "supply",
  ENGINEER: "engineer",
  ACCOUNTANT: "accountant",
};

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

async function at(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
}

/** Новый вход на каждой ширине: сессия мока — в `localStorage` страницы, её убираем перед входом. */
async function signInAt(page: Page, role: Role, width: number): Promise<void> {
  await at(page, width);
  if (page.url().startsWith("http")) {
    await page.evaluate(`window.localStorage.removeItem("rt-pf-mock-session")`);
  }
  await loginAndWait(page, EMAIL[role]);
}

test.describe("P8: роли пилота и регистрация входящих", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const role of PILOT_ROLES) {
    test(`меню роли «${ROLE_NAMES[role]}»: модули по матрице, 1440 и 390`, async ({ page }) => {
      for (const width of WIDTHS) {
        await signInAt(page, role, width);
        if (width >= 768) {
          await expect(railLinks(page)).toHaveText(visibleModules(role));
        }
        await expect(
          page.getByRole("button", { name: /профиль и настройки/i }),
        ).toHaveAccessibleName(new RegExp(`${ROLE_NAMES[role]}: профиль и настройки`));
        await shot(page, `menu-${SLUG[role]}`);
        await expectNoViolations(page, `${role} ${String(width)}`);
      }
    });
  }

  test("делопроизводитель регистрирует требование ГНК: дубль, «срочно», ВХ-номер, без резолюции", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, "REGISTRAR", width);
      await spaGoto(page, "/eds/inbox");
      await expect(page.getByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
      await page.getByRole("link", { name: "Зарегистрировать входящее" }).click();
      await expect(
        page.getByRole("heading", { level: 1, name: "Зарегистрировать входящее" }),
      ).toBeVisible();
      await shot(page, "register-form-empty");
      await expectNoViolations(page, `форма ${String(width)}`);

      await chooseOption(page.getByLabel("Вид документа"), "Требование или уведомление ГНК");
      await expect(page.getByRole("checkbox", { name: "Срочно" })).toBeChecked();
      await page.getByLabel("Корреспондент", { exact: true }).fill("ГНИ Демо-района");
      await page.getByLabel("Исходящий номер отправителя").fill("04-12/3456");
      // тот же корреспондент и исходящий номер — предупреждение со ссылкой на ВХ-108/26
      await expect(page.getByText(/Возможно, это письмо уже зарегистрировано/)).toBeVisible();
      await expect(page.getByRole("link", { name: "ВХ-108/26" })).toBeVisible();
      await page.getByLabel("Исходящий номер отправителя").fill("04-12/4100");
      await page.getByLabel("Подписал").fill("Начальник инспекции Демо Налогов");
      await page.getByLabel("Тема").fill("Требование о представлении пояснений по НДС за октябрь");
      await pickFiles(page.getByLabel("Файл документа"), {
        name: "trebovanie.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-1.4 demo"),
      });
      await expect(page.getByText("загружен")).toBeVisible();
      await shot(page, "register-form-filled");
      await expectNoViolations(page, `заполненная форма ${String(width)}`);

      const started = Date.now();
      await page.getByRole("button", { name: "Зарегистрировать", exact: true }).click();
      await expect(page.getByText(/Зарегистрировано: ВХ-109\/26/)).toBeVisible();
      expect(Date.now() - started).toBeLessThan(60_000);
      await expect(page.getByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
      // письмо в боковом окне (на телефоне — лист): ждёт резолюции директора, у делопроизводителя кнопки решения нет
      await expect(page.getByText("Письмо ждёт резолюции директора")).toBeVisible();
      await expect(page.getByRole("button", { name: /Утвердить резолюцию/ })).toHaveCount(0);
      await shot(page, "register-done");
      await expectNoViolations(page, `после регистрации ${String(width)}`);
    }
  });

  test("директор: ВХ «Ждёт резолюции» в «Моих задачах» и форма резолюции в карточке", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, "DIRECTOR", width);
      const row = page
        .getByRole("region", { name: "Что сделать сейчас" })
        .getByRole("listitem")
        .filter({ hasText: "Наложить резолюцию на письмо ВХ-108/26" });
      await expect(row).toBeVisible();
      await expect(row).toContainText("ГНИ Демо-района");
      await shot(page, "director-queue");

      await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution");
      await expect(page.getByRole("heading", { level: 1, name: /ВХ-108\/26/ })).toBeVisible();
      await expect(page.getByText("Требование или уведомление ГНК")).toBeVisible();
      await expect(page.getByText("Кабинет налогоплательщика my.soliq")).toBeVisible();
      if (width >= 768) {
        await expect(page.getByRole("button", { name: /Утвердить резолюцию/ })).toBeVisible();
      } else {
        await expect(page.getByRole("button", { name: "Наложить резолюцию" })).toBeVisible();
      }
      await shot(page, "director-letter");
      await expectNoViolations(page, `карточка ВХ директора ${String(width)}`);
    }
  });

  test("менеджер-универсал: расчёт, проекты, счета и оплаты открыты; регистрации и резолюции нет", async ({
    page,
  }) => {
    await signInAt(page, "MANAGER_ALL", 1440);
    for (const path of ["/erp/calc", "/eds/projects", "/eds/payments"]) {
      await spaGoto(page, path);
      await expect(page.getByRole("main").getByRole("heading").first(), path).toBeVisible();
      await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" }), path).toHaveCount(
        0,
      );
    }
    await spaGoto(page, "/eds/inbox");
    await expect(page.getByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Зарегистрировать входящее" })).toHaveCount(0);
    await spaGoto(page, "/eds/register");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
  });
});
