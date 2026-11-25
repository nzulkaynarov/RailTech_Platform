import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, reveal, spaGoto, waitForMotionEnd } from "./support/app";
import { addAddressee, chooseOption, fillDate, openStep, pickFiles } from "./support/fields";

// СЦ-11 «Входящее: регистрация и ответ» на MSW: требование ГНК не регистрируется без срока (срок подсказан по файлу),
// шаг «Проверка» показывает сводку, карточка письма не по сделке без строк заявки и клиента, ответ ссылается на номер и дату
// отправителя. Обе ширины, axe.
const WIDTHS = [1440, 390] as const;

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

async function signInAt(page: Page, email: string, width: number): Promise<void> {
  await at(page, width);
  if (page.url().startsWith("http")) {
    await page.evaluate(`window.localStorage.removeItem("rt-pf-mock-session")`);
  }
  await loginAndWait(page, email);
}

test.describe("СЦ-11 · Входящее: регистрация и ответ", () => {
  test("делопроизводитель: срок требования ГНК обязателен и подсказан, «Проверка» со сводкой", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    for (const width of WIDTHS) {
      await signInAt(page, "registrar@demo.example", width);
      await spaGoto(page, "/eds/register");
      await expect(
        page.getByRole("heading", { level: 1, name: "Регистрация входящего документа" }),
      ).toBeVisible();
      await chooseOption(
        await reveal(page.getByLabel("Вид документа")),
        "Требование или уведомление ГНК",
      );
      await reveal(page.getByLabel("Корреспондент (организация)", { exact: true }));
      await addAddressee(page, "ГНИ Сводного района", "", "Корреспондент (организация)");
      await (await reveal(page.getByLabel("Исходящий номер отправителя"))).fill("01-12/345");
      await (
        await reveal(page.getByLabel("Тема", { exact: true }))
      ).fill("Требование о представлении пояснений");
      await pickFiles(await reveal(page.getByLabel("Файл документа")), {
        name: "trebovanie.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-1.4 demo"),
      });
      await expect(page.getByText("загружен")).toBeVisible();

      // срок подсказан по файлу (помощник), помечен «Предложено ИИ»; человек стёр его — без срока не зарегистрировать
      await openStep(page, "Срок, адресат и резолюция");
      const due = page.getByLabel("Срок по документу");
      await expect(due).not.toHaveValue("");
      await shot(page, "register-due-suggested");
      await page
        .locator(".ant-picker", { has: page.locator("#reg-document-due") })
        .locator(".ant-picker-clear")
        .click({ force: true });
      await expect(due).toHaveValue("");
      await openStep(page, "Проверка и регистрация");
      await expect(
        page
          .locator("#reg-remaining")
          .getByText("Для этого вида документа нужен срок по документу"),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Зарегистрировать", exact: true }),
      ).toBeDisabled();
      await shot(page, "register-review-blocked");
      await expectNoViolations(page, `проверка без срока ${String(width)}`);

      await openStep(page, "Срок, адресат и резолюция");
      await shot(page, "register-due-required");
      await fillDate(page.getByLabel("Срок по документу"), "2026-11-30");
      await openStep(page, "Проверка и регистрация");
      const summary = page.locator(".pf-reg-summary");
      await expect(summary).toContainText("ГНИ Сводного района");
      await expect(summary).toContainText("01-12/345");
      await expect(summary).toContainText("30.11.2026");
      await expect(summary).not.toContainText("Связь с заявкой");
      await expect(
        page.getByRole("button", { name: "Зарегистрировать", exact: true }),
      ).toBeEnabled();
      await shot(page, "register-review-summary");
      await expectNoViolations(page, `проверка со сводкой ${String(width)}`);
    }
  });

  for (const width of [1512, 1440, 390] as const) {
    test(`модель выключена: срок по тексту письма считает код и метит «Из текста письма» (${String(width)})`, async ({
      page,
    }) => {
      await signInAt(page, "registrar@demo.example", width);
      await spaGoto(page, "/eds/register");
      await page.evaluate(
        `window.localStorage.setItem("rt-pf-mock-docflow-settings", JSON.stringify({recognize_scans: true, pii_policy: "business", ai_available: false, author_may_sign_own_letter: true}))`,
      );
      await spaGoto(page, "/eds/register");
      // панель «Заполнить из файла» видна и без модели: код читает срок из текста PDF
      await expect(page.getByRole("button", { name: "Заполнить из файла" })).toBeVisible();
      await pickFiles(await reveal(page.getByLabel("Файл документа")), {
        name: "rules-trebovanie.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-1.4 demo"),
      });
      await expect(page.getByText("загружен")).toBeVisible();
      await expect(
        page.getByRole("status").filter({ hasText: "Подставлено из текста письма" }),
      ).toBeVisible();
      await shot(page, "rules-banner");
      await openStep(page, "Срок, адресат и резолюция");
      await expect(page.locator("button[aria-expanded]", { hasText: "Файл письма" })).toContainText(
        "Подставлено из текста письма",
      );
      await expect(page.getByLabel("Срок по документу")).not.toHaveValue("");
      await expect(page.getByText("Из текста письма", { exact: true })).toBeVisible();
      await expect(page.getByText("Предложено ИИ", { exact: true })).toHaveCount(0);
      await shot(page, "rules-label");
      await expectNoViolations(page, `срок по тексту письма ${String(width)}`);
    });
  }

  test("модель ответила, срок посчитал код: у срока своя метка, у остальных «Предложено ИИ»", async ({
    page,
  }) => {
    await signInAt(page, "registrar@demo.example", 1440);
    await spaGoto(page, "/eds/register");
    await pickFiles(await reveal(page.getByLabel("Файл документа")), {
      name: "mixed-trebovanie.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 demo"),
    });
    await expect(page.getByText("загружен")).toBeVisible();
    await openStep(page, "Срок, адресат и резолюция");
    await expect(page.getByLabel("Срок по документу")).not.toHaveValue("");
    // срок посчитал код, остальные шесть полей предложила модель (у ИНН своей метки на экране нет)
    await expect(page.getByText("Из текста письма", { exact: true })).toHaveCount(1);
    await expect(page.getByText("Предложено ИИ", { exact: true })).toHaveCount(6);
    await expect(page.locator("button[aria-expanded]", { hasText: "Файл письма" })).toContainText(
      "проверьте отмеченные поля",
    );
    await expect(
      page.locator("button[aria-expanded]", { hasText: "Файл письма" }),
    ).not.toContainText("Предложено ИИ");
    await shot(page, "mixed-labels");
    await expectNoViolations(page, "смешанный ответ");
  });

  test("дата поступления изменилась — срок от кода предлагают пересчитать (без модели), правленый руками не трогают", async ({
    page,
  }) => {
    await signInAt(page, "registrar@demo.example", 1440);
    await spaGoto(page, "/eds/register");
    await pickFiles(await reveal(page.getByLabel("Файл документа")), {
      name: "rules-trebovanie.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 demo"),
    });
    await expect(page.getByText("загружен")).toBeVisible();
    const day = (offset: number) => {
      const d = new Date(Date.now() + offset * 86_400_000);
      return d.toISOString().slice(0, 10);
    };
    await fillDate(await reveal(page.getByLabel("Дата поступления")), day(-3));
    await openStep(page, "Файл письма");
    const recompute = page.getByRole("button", { name: "Пересчитать срок" });
    await expect(recompute).toBeVisible();
    await recompute.click();
    await expect(recompute).toHaveCount(0);
    await openStep(page, "Срок, адресат и резолюция");
    const [y, m, d] = day(4).split("-");
    await expect(page.getByLabel("Срок по документу")).toHaveValue(`${d}.${m}.${y}`);
    // срок поправили руками — смена даты поступления его больше не трогает и пересчёт не предлагает
    await expect(async () => {
      await fillDate(page.getByLabel("Срок по документу"), day(20));
    }).toPass();
    await fillDate(await reveal(page.getByLabel("Дата поступления")), day(-2));
    await openStep(page, "Файл письма");
    await expect(page.getByRole("button", { name: "Пересчитать срок" })).toHaveCount(0);
  });

  test("карточка письма не по сделке без полей заявки и клиента; ответ «На № …» отправителя", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    for (const width of WIDTHS) {
      await signInAt(page, "director@demo.example", width);
      await spaGoto(page, `/eds/inbox/${encodeURIComponent("ВХ-108/26")}?panel=open&tab=facts`);
      // ЕД-7: связи — строки «Сведений» бокового окна
      await expect(page.locator("dt", { hasText: /^Зарегистрировано$/ })).toBeVisible();
      await expect(page.getByText("Клиент не определён")).toHaveCount(0);
      await expect(page.locator("dt", { hasText: /^Заявка$/ })).toHaveCount(0);
      await shot(page, "letter-card-no-deal");
      await expectNoViolations(page, `карточка ${String(width)}`);

      await spaGoto(page, "/eds/inbox");
      await page.getByRole("link", { name: "Показать письмо ВХ-108/26 в боковом окне" }).click();
      const brief = page.getByRole("region", { name: "ВХ-108/26" });
      await expect(brief).toBeVisible();
      await expect(brief.locator("dt", { hasText: /^Заявка$/ })).toHaveCount(0);
      await shot(page, "panel-brief-no-deal");
      await expectNoViolations(page, `боковое окно ${String(width)}`);

      await spaGoto(
        page,
        `/eds/new?type=letter&reply_to=${encodeURIComponent("ВХ-108/26")}&reply_id=20000000-0000-4000-8000-000000000108`,
      );
      await expect(page.getByLabel("В ответ на входящее")).toHaveValue("ВХ-108/26");
      await expect(page.getByLabel("Тема", { exact: true })).toHaveValue(
        /^На № 04-12\/3456 от 28\.10\.2026: /,
      );
      await shot(page, "reply-card");
      await expectNoViolations(page, `ответ ${String(width)}`);
    }
  });
});
