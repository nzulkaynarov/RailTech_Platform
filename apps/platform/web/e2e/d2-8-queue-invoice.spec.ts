import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// D2-8 на MSW (план 2026-11-01 §6 п. 3; SPEC-v3 §1.2 п. 3, §4.1): утром у менеджера-универсала в «Моих задачах» — расчёт,
// платёжка на подтверждение, счёт к выставлению и договор, ждущий скана; каждая строка открывает экран, где это делается.
// «Выставить счёт» из Платформы (B-D24-4) с правдивым «Что произойдёт»; номер ЗВ из письма открывает заявку (B-UIA-1).
// Обе ширины, axe WCAG 2.1 AA — 0 нарушений.
const WIDTHS = [1440, 390] as const;
const UNIVERSAL = "universal@demo.example";

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

async function signInAt(page: Page, email: string, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    await page.evaluate(`window.localStorage.clear()`);
  }
  await loginAndWait(page, email);
}

function queueRow(page: Page, title: string | RegExp) {
  return page
    .getByRole("region", { name: "Что сделать сейчас" })
    .getByRole("listitem")
    .filter({ hasText: title });
}

test.describe("D2-8: «Мои задачи» менеджера-универсала и «Выставить счёт»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`утро менеджера-универсала: четыре вида работы ERP, у каждого — свой экран, ${String(width)}`, async ({
      page,
    }) => {
      await signInAt(page, UNIVERSAL, width);
      const rows = {
        calc: queueRow(page, "Начать расчёт по заявке ЗВ-2026-103"),
        pay: queueRow(page, "Подтвердить оплату по счёту СЧ-2026/145"),
        issue: queueRow(page, "Выставить счёт СЧ-2026/143"),
        scan: queueRow(page, "Прикрепить скан подписанного договора ДОГ-2026/106"),
      };
      for (const row of Object.values(rows)) await expect(row).toHaveCount(1);
      await shot(page, "queue-manager-all");
      await expectNoViolations(page, `очередь ${String(width)}`);

      await rows.calc.getByRole("link", { name: /Открыть/ }).click();
      await expect(page).toHaveURL(/\/erp\/calc\/%D0%97%D0%92-2026-103$/);
      await expect(page.getByRole("heading", { level: 1, name: /ЗВ-2026-103/ })).toBeVisible();

      await spaGoto(page, "/dashboard/queue");
      await rows.pay.getByRole("link", { name: /Открыть/ }).click();
      await expect(page).toHaveURL(/\/eds\/payments\/145\?/);
      await expect(page.getByRole("heading", { level: 1, name: "СЧ-2026/145" })).toBeVisible();

      await spaGoto(page, "/dashboard/queue");
      await rows.scan.getByRole("link", { name: /Открыть/ }).click();
      await expect(page).toHaveURL(/\/eds\/projects\/%D0%9F%D0%A0-2026-106/);
      await expect(
        page.getByRole("heading", { level: 1, name: "Проект ПР-2026-106" }),
      ).toBeVisible();
      if (width >= 768) {
        // вкладка «Договор» бокового окна: шаг «Прикрепить подписанный скан»
        await expect(page.getByRole("button", { name: /Прикрепить скан/ }).first()).toBeVisible();
      }
      await shot(page, "contract-scan");
      await expectNoViolations(page, `договор ждёт скана ${String(width)}`);
    });

    test(`директор: в «Моих задачах» только решения, строк исполнения ERP нет, ${String(width)}`, async ({
      page,
    }) => {
      await signInAt(page, "director@demo.example", width);
      await expect(queueRow(page, "Наложить резолюцию на письмо ВХ-104/26")).toHaveCount(1);
      for (const title of [
        /Начать расчёт|Завизировать строки|Отправить директору расчёт|Доработать расчёт/,
        /Подтвердить оплату/,
        /Выставить счёт/,
        /проект договора|договор ДОГ|скан подписанного/,
        /Выпустить (заново )?акт/,
      ]) {
        await expect(queueRow(page, title)).toHaveCount(0);
      }
      await shot(page, "queue-director");
      await expectNoViolations(page, `очередь директора ${String(width)}`);
    });

    test(`«Выставить счёт» из «Моих задач»: черновик → «Выставлен», ${String(width)}`, async ({
      page,
    }) => {
      await signInAt(page, UNIVERSAL, width);
      await queueRow(page, "Выставить счёт СЧ-2026/143")
        .getByRole("link", { name: /Открыть/ })
        .click();
      await expect(page).toHaveURL(/\/eds\/payments\/143/);
      // на телефоне окно «Оплата» — лист на весь экран (ссылка очереди открывает его сразу)
      const form = page.getByRole("form", { name: "Выставить счёт" });
      await expect(form).toBeVisible();
      const what = form.getByRole("group", { name: "Что произойдёт" });
      await expect(what).toContainText("«Выставлен»");
      await expect(what).toContainText("PDF с реквизитами компании");
      await expect(what).toContainText("увидит счёт в кабинете");
      await shot(page, "invoice-issue");
      await expectNoViolations(page, `выставить счёт ${String(width)}`);

      await form.getByRole("button", { name: "Выставить счёт" }).click();
      await expect(page.getByText("Счёт СЧ-2026/143 выставлен.").first()).toBeVisible();
      await expect(page.getByText("Выставлен", { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("form", { name: "Выставить счёт" })).toHaveCount(0);
      await shot(page, "invoice-issued");

      // строка ушла из очереди: счёт больше не ждёт выставления
      await spaGoto(page, "/dashboard/queue");
      await expect(queueRow(page, "Подтвердить оплату по счёту СЧ-2026/145")).toHaveCount(1);
      await expect(queueRow(page, "Выставить счёт СЧ-2026/143")).toHaveCount(0);
    });

    test(`номер ЗВ в письме открывает заявку, а не заглушку (B-UIA-1), ${String(width)}`, async ({
      page,
    }) => {
      await signInAt(page, "director@demo.example", width);
      // карточка письма без бокового окна: блок «Связи» с номером заявки
      await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-104%2F26");
      const link = page.getByRole("link", { name: "ЗВ-2026-104" }).first();
      await expect(link).toHaveAttribute(
        "href",
        "/erp/requests?request=%D0%97%D0%92-2026-104&panel=open&tab=task",
      );
      // окно «Резолюция» на широком экране лежит поверх карточки — закрываем, как сделал бы сотрудник
      if (width >= 768) {
        await page.getByRole("button", { name: "Скрыть панель", exact: true }).click();
        await waitForMotionEnd(page);
      }
      await link.click();
      await expect(page).toHaveURL(/\/erp\/requests\?request=/);
      await expect(page.getByRole("heading", { level: 1, name: "Заявки в расчёте" })).toBeVisible();
      await expect(page.getByText("в старом ERP")).toHaveCount(0);
      await shot(page, "request-from-letter");
      await expectNoViolations(page, `заявка из письма ${String(width)}`);
    });

    test(`поиск по номеру ЗВ открывает заявку с заданием, а не подсказку «в старом ERP» (B-UIA-1), ${String(width)}`, async ({
      page,
    }) => {
      await signInAt(page, UNIVERSAL, width);
      const search = page.getByRole("combobox", { name: "Глобальный поиск" });
      await search.click();
      await search.fill("ЗВ-2026-097");
      await expect(page.getByRole("option", { name: /ЗВ-2026-097/ })).toBeVisible();
      await search.press("ArrowDown");
      await search.press("Enter");
      await expect(page).toHaveURL(/\/erp\/requests\?request=%D0%97%D0%92-2026-097/);
      await expect(page.getByRole("region", { name: "Где посмотреть" })).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Резолюция директора" })).toBeVisible();
      await expect(
        page.getByRole("link", { name: "Открыть расчёт", exact: true }).last(),
      ).toBeVisible();
      await shot(page, "request-from-search");
      await expectNoViolations(page, `заявка из поиска ${String(width)}`);
    });
  }
});

// D26G-6, D26G-9 (гейт D2-6): реквизитов компании нет — менеджер-универсал видит это до клика, на вкладке «К выставлению» и у
// кнопки «Выставить счёт» (неактивна), без ссылки в закрытые для него Настройки; служебка на шаге «Бухгалтер» — строка
// «Принять к оплате» в его «Моих задачах». Снимки — docs/screens/d26g-4.
test.describe("D26G-6, D26G-9: реквизиты для счёта и служебка к оплате у менеджера-универсала", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`нет реквизитов — видно до клика; служебка к оплате — в «Моих задачах», ${String(width)}`, async ({
      page,
    }) => {
      await signInAt(page, UNIVERSAL, width);
      const memo = queueRow(page, /Принять к оплате СЗ-2026\/015/);
      await expect(memo).toHaveCount(1);
      await memo.scrollIntoViewIfNeeded();
      await shot(page, "queue-manager-all-pay-memo");

      await page.evaluate(`window.localStorage.setItem("rt-pf-mock-no-bank", "1")`);
      await spaGoto(page, "/eds/payments?show=to_issue");
      const main = page.getByRole("main");
      await expect(
        main.getByText("Нет банковских реквизитов компании — счёт не выставить."),
      ).toBeVisible();
      await expect(
        main.getByText("Заполняет администратор: Настройки · Компания и бланки."),
      ).toBeVisible();
      await expect(page.getByRole("link", { name: "Открыть «Компания и бланки»" })).toHaveCount(0);
      await shot(page, "payments-to-issue-no-bank");
      await expectNoViolations(page, `к выставлению без реквизитов ${String(width)}`);

      await spaGoto(page, "/eds/payments/143?panel=open&tab=payment");
      const form = page.getByRole("form", { name: "Выставить счёт" }).first();
      await expect(
        form.getByText("Нет банковских реквизитов компании — счёт не выставить."),
      ).toBeVisible();
      await expect(form.getByRole("button", { name: "Выставить счёт" })).toBeDisabled();
      await shot(page, "invoice-issue-no-bank");
      await expectNoViolations(page, `карточка счёта без реквизитов ${String(width)}`);
    });
  }
});
