import { expect, test, type Page } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { chooseOrAddAddressee } from "./support/fields";

// ВХОД-1: «Заявка клиента» и «Подключение партнёра» — действия самой карточки входящего письма, а не пункты меню «Ещё»
// у поручения. Компания-отправитель без карточки клиента не тупик: карточка заводится вместе с заявкой. Недоступное
// действие стоит на месте и называет причину. Снимки 1440 и 390 с axe — docs/screens/vhod1.
const LETTER = "ВХ-108/26";
const SENDER = "ГНИ Демо-района";

async function openLetter(page: Page, email: string): Promise<void> {
  await loginAndWait(page, email);
  await spaGoto(page, `/eds/inbox/${encodeURIComponent(LETTER)}`);
  await expect(page.getByRole("heading", { level: 1, name: `Письмо ${LETTER}` })).toBeVisible();
}

for (const width of [1440, 390] as const) {
  test.describe(`карточка письма, ${String(width)}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    });

    test("действия видны сразу, без резолюции и без «Ещё»; у кого нет права — причина рядом", async ({
      page,
    }) => {
      await openLetter(page, "manager@demo.example");
      const block = page.getByRole("region", { name: "Создать из письма" });
      await expect(block.getByRole("button", { name: "Заявка клиента" })).toBeEnabled();
      const partner = block.getByRole("button", { name: "Подключение партнёра" });
      await expect(partner).toBeDisabled();
      await expect(block.getByText("Нет доступа к снабжению", { exact: false })).toBeVisible();
      await expect(page.getByRole("button", { name: "Ещё" })).toHaveCount(0);
      await settledScreenshot(page, "letter-card-actions");
      await expectNoViolations(page, `карточка письма с действиями ${String(width)}`);
    });

    test("заявка клиента из письма для компании без карточки клиента: форма, «Заявка создана»", async ({
      page,
    }) => {
      await openLetter(page, "universal@demo.example");
      await page.getByRole("button", { name: "Заявка клиента" }).click();
      const sheet = page.getByRole("dialog", { name: `${LETTER}: заявка клиента` });
      // название отправителя стоит в поле серым; выбираем компанию (карточки клиента у неё нет)
      await expect(sheet.locator(".ant-select-selection-placeholder")).toHaveText(SENDER);
      await chooseOrAddAddressee(page, SENDER, "Название компании");
      await expect(sheet.getByText(/заведёт/)).toBeVisible();
      await settledScreenshot(page, "letter-request-company");
      await expectNoViolations(page, `форма заявки из письма ${String(width)}`);

      await sheet.getByRole("button", { name: /^Контакт/, expanded: false }).click();
      await sheet.getByLabel("Имя").fill("Азиз Демо");
      await sheet.getByLabel("Почта").fill("aziz@example.com");
      // карточки клиента и лида нет: согласие на данные отмечает сотрудник, из письма — «Письмом»
      await sheet.getByLabel("Согласие получено").check();
      await expect(sheet.getByText("Письмом", { exact: false }).first()).toBeVisible();
      await settledScreenshot(page, "letter-request-consent");
      await expectNoViolations(page, `согласие в заявке из письма ${String(width)}`);
      await sheet.getByRole("button", { name: /^Проверка и отправка/, expanded: false }).click();
      await sheet.getByRole("button", { name: /Создать заявку/ }).click();
      await expect(sheet.getByText("Заявка создана")).toBeVisible();
      await settledScreenshot(page, "letter-request-created");
      await expectNoViolations(page, `заявка из письма создана ${String(width)}`);

      // форма закрыта: второй заявки по этому письму не создать, причина рядом с серой кнопкой
      await sheet.getByRole("button", { name: "Закрыть" }).last().click();
      await expect(sheet).toBeHidden();
      await expect(page.getByRole("button", { name: "Заявка клиента" })).toBeDisabled();
      await expect(page.getByText("Заявка по письму уже создана.")).toBeVisible();
    });

    test("подключение партнёра из письма: форма с компанией, заявка в очереди", async ({
      page,
    }) => {
      await openLetter(page, "universal@demo.example");
      await page.getByRole("button", { name: "Подключение партнёра" }).click();
      const form = page.getByRole("dialog", { name: `${LETTER}: подключение партнёра` });
      await expect(form.getByLabel("Компания")).toHaveValue(SENDER);
      await form.getByLabel("Контактное лицо").fill("Анвар Колёсов");
      await form.getByLabel("Почта").fill("wheels@example.com");
      await settledScreenshot(page, "letter-partner-form");
      await expectNoViolations(page, `форма подключения партнёра ${String(width)}`);
      await form.getByRole("button", { name: "Создать заявку" }).click();
      await expect(
        page.getByText(`По письму ${LETTER} создана заявка на подключение партнёра`),
      ).toBeVisible();
    });

    test("в боковом окне письма во «Входящих» действия тоже вверху", async ({ page }) => {
      test.skip(width < 768, "на телефоне лист «Резолюция» — на весь экран, действия в карточке");
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/eds/inbox");
      await page
        .getByRole("row")
        .filter({
          has: page.getByRole("link", { name: `Показать письмо ${LETTER} в боковом окне` }),
        })
        .getByText(SENDER)
        .click();
      const panel = page.locator("#pf-context-panel");
      await expect(panel.getByRole("button", { name: "Заявка клиента" })).toBeEnabled();
      await expect(panel.getByRole("button", { name: "Подключение партнёра" })).toBeDisabled();
      await expect(panel.getByText("Нет доступа к снабжению", { exact: false })).toBeVisible();
      await expect(page.locator("main .ant-btn-primary:visible")).toHaveCount(0);
      await settledScreenshot(page, "letter-drawer-actions");
      await expectNoViolations(page, `боковое окно письма ${String(width)}`);
    });
  });
}
