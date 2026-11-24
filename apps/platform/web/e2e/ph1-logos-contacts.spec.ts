import { expect, test } from "@playwright/test";
import { deflateSync } from "node:zlib";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕД-5 и СУЩ-3 на MSW: логотип контрагента и фото контакта грузятся в карточке (нажать на картинку → файл → обрезка →
// сохранить), видны в списке «Контрагенты»; фото сотрудников — в «Сотрудниках». Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];
/** PNG 120×90 из двух цветов (синий фон, белая «шпала» и рельс) — настоящий файл, который читает обрезка. */
function makePng(width = 120, height = 90): Buffer {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (bytes: Buffer) => {
    let c = 0xffffffff;
    for (const byte of bytes) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const out = Buffer.alloc(8 + data.length + 4);
    out.writeUInt32BE(data.length, 0);
    body.copy(out, 4);
    out.writeUInt32BE(crc(body), 8 + data.length);
    return out;
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 2, 0, 0, 0], 8);
  const rows: Buffer[] = [];
  for (let y = 0; y < height; y += 1) {
    const row = Buffer.alloc(1 + width * 3);
    for (let x = 0; x < width; x += 1) {
      const light = (y > 58 && y < 66) || (x > 54 && x < 66 && y > 20);
      row.set(light ? [255, 255, 255] : [20, 100, 160], 1 + x * 3);
    }
    rows.push(row);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
const PNG = makePng();

async function pickAndSave(
  page: import("@playwright/test").Page,
  inputLabel: string | RegExp,
  dialogName: string,
  save: string,
) {
  await page
    .getByLabel(inputLabel)
    .first()
    .setInputFiles({ name: "picture.png", mimeType: "image/png", buffer: PNG });
  const dialog = page.getByRole("dialog", { name: dialogName });
  await expect(dialog.locator("img")).toBeVisible();
  const apply = dialog.getByRole("button", { name: save });
  await expect(apply).toBeEnabled();
  return { dialog, apply };
}

for (const width of [1440, 390] as const) {
  test(
    `логотип и фото контакта в карточке контрагента, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/clients/3?panel=open&tab=card");
      const head = page.locator(".pf-cp-head");
      await expect(head.getByRole("heading", { name: "ООО Рельс-Сервис Демо" })).toBeVisible();
      await expect(head.locator("img")).toHaveCount(0);
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/card-letters-${String(width)}.png` });

      // логотип: буквы → выбор файла → квадратная обрезка → сохранить
      const logo = await pickAndSave(
        page,
        /^Файл логотипа$/,
        "Логотип компании",
        "Сохранить логотип",
      );
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/logo-crop-${String(width)}.png` });
      await expectNoViolations(page, "обрезка логотипа");
      await logo.apply.click();
      await expect(head.locator("img")).toHaveAttribute("src", /\/logo\?v=v\d+$/);
      await expect(head.getByRole("button", { name: "Убрать логотип" })).toBeVisible();

      // фото контакта — в «Обзоре»
      await page.getByRole("tab", { name: "Обзор" }).click();
      await expect(page.getByRole("heading", { name: "Люди" })).toBeVisible();
      const photo = await pickAndSave(page, /^Файл фото: /, "Фото контакта", "Сохранить фото");
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/photo-crop-${String(width)}.png` });
      await expectNoViolations(page, "обрезка фото контакта");
      await photo.apply.click();
      await expect(page.locator(".pf-cp-list .pf-entity__pic img").first()).toHaveAttribute(
        "src",
        /\/photo\?v=v\d+$/,
      );
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/card-uploaded-${String(width)}.png` });
      await expectNoViolations(page, "карточка с логотипом и фото");

      // список «Контрагенты» показывает тот же логотип
      await spaGoto(page, "/crm/clients");
      // на 1440 — строка таблицы, на 390 — карточка списка: логотип один и тот же
      await expect(page.locator('img[src*="/counterparties/1003/logo?v=v"]').first()).toBeVisible();
      if (dir) await page.screenshot({ path: `${dir}/clients-list-${String(width)}.png` });
      await expectNoViolations(page, "список контрагентов с логотипом");
    },
  );

  test(
    `фото сотрудников в таблице «Сотрудники», ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/me");
      await expect(page.getByRole("heading", { level: 1, name: "Профиль" })).toBeVisible();
      const own = await pickAndSave(page, /^Загрузить фото$/, "Фото профиля", "Сохранить фото");
      await own.apply.click();
      await expect(page.getByText("Фото обновлено")).toBeVisible();

      await spaGoto(page, "/admin/org");
      await expect(page.getByRole("heading", { level: 1, name: "Сотрудники" })).toBeVisible();
      await expect(page.locator(".pf-entity__pic img").first()).toHaveAttribute(
        "src",
        /\/staff\/u-demo-admin\/avatar\?v=\d+$/,
      );
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/employees-${String(width)}.png` });
      await expectNoViolations(page, "сотрудники с фото");
    },
  );
}
