import type { Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";

/**
 * Поля Платформы в e2e (UX-2a): системных `input type="date|file"` и `<select>` нет — дата `DateField` (antd DatePicker,
 * `ДД.ММ.ГГГГ`), файл `FileField`/`FilePicker` (кнопка «Выбрать файл», системное поле скрыто), выбор — antd `Select`.
 */

/** Набрать дату в `DateField` с клавиатуры, как сотрудник: ключ `YYYY-MM-DD` → `ДД.ММ.ГГГГ`, Enter. Пусто — очистить. */
export async function fillDate(field: Locator, iso: string): Promise<void> {
  await field.click();
  if (iso === "") {
    await field.fill("");
    await field.press("Enter");
    return;
  }
  const text = iso.split("-").reverse().join(".");
  // Поле только что раскрытого шага под нагрузкой иногда не принимает первый набор (Enter не доходит до календаря):
  // набираем заново, пока значение не встанет.
  await expect(async () => {
    await field.click();
    await field.fill(text);
    await field.press("Enter");
    await expect(field).toHaveValue(text, { timeout: 2_000 });
  }).toPass({ timeout: 15_000 });
}

type FilePayload = Parameters<Locator["setInputFiles"]>[0];

/**
 * Выбрать файлы в `FileField`/`FilePicker`: `field` — поле по подписи (`getByLabel("Вложения")`), оно скрыто за кнопкой
 * «Выбрать файл», поэтому файлы кладутся в него напрямую — как после выбора в системном диалоге.
 */
export async function pickFiles(field: Locator, files: FilePayload): Promise<void> {
  await expect(field).toHaveAttribute("type", "file");
  await field.setInputFiles(files);
}

/**
 * Выбрать пункт antd `Select` по подписи пункта (`title`) с клавиатуры, как сотрудник без мыши: фокус, ↓ открывает список,
 * ↓ до нужного пункта, Enter. `field` — поле по подписи (`getByLabel("Домен")`) или `getByRole("combobox", …)`. Клавиатура,
 * а не щелчок: ячейка матрицы ролей может лежать под боковым окном, а подпись выбранного пункта — поверх поля поиска.
 */
export async function chooseOption(field: Locator, label: string): Promise<void> {
  const page = field.page();
  // Поля нет на экране — понятный отказ сразу, а не зависание цикла ниже до его общего таймаута.
  await expect(field).toBeVisible();
  const selected = field
    .locator("xpath=ancestor::div[contains(concat(' ', @class, ' '), ' ant-select ')][1]")
    .locator(".ant-select-selection-item");
  // Поле может перерисоваться посреди выбора (черновик роли в матрице меняет подписи столбца) — тогда Enter уходит мимо.
  // Выбор целиком повторяется, пока подпись выбранного не станет нужной.
  await expect(async () => {
    // пустое поле (подсказка вместо выбранного) — подписи нет; `getAttribute` ждал бы её до конца теста
    if ((await selected.count()) > 0 && (await selected.first().getAttribute("title")) === label) {
      return;
    }
    await field.focus();
    await field.press("ArrowDown");
    // свой список — по `aria-controls` поля: закрывающийся список соседнего поля ещё в DOM, пока идёт анимация
    const listId = await field.getAttribute("aria-controls");
    expect(listId, "у поля antd Select есть aria-controls").toBeTruthy();
    const dropdown = page.locator(".ant-select-dropdown").filter({
      has: page.locator(`[id="${listId ?? ""}"]`),
    });
    await expect(dropdown).toBeVisible({ timeout: 3_000 });
    const option = dropdown.locator(`.ant-select-item-option[title="${label}"]`);
    if ((await option.count()) > 0 && (await option.first().isVisible())) {
      await option.first().click();
    } else {
      const active = dropdown.locator(".ant-select-item-option-active");
      // список виртуальный: в DOM не все пункты — шагов не больше полусотни
      for (let step = 0; step < 50; step += 1) {
        if ((await active.getAttribute("title")) === label) break;
        await field.press("ArrowDown");
      }
      await expect(active).toHaveAttribute("title", label, { timeout: 1_000 });
      await field.press("Enter");
    }
    await expect(selected).toHaveAttribute("title", label, { timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
}

/**
 * Открыть шаг формы по секциям (`StepSections`, platform-frontend.md §4.1a): щелчок по заголовку секции, если она свёрнута.
 * Заголовок — кнопка с `aria-expanded`; кнопка «Далее: <шаг>» его не имеет, поэтому с ней не путается.
 */
export async function openStep(page: Page, title: string | RegExp): Promise<void> {
  const head = page.locator("button[aria-expanded]", { hasText: title }).first();
  if ((await head.getAttribute("aria-expanded")) !== "true") await head.click();
  await expect(head).toHaveAttribute("aria-expanded", "true");
}

/** Поле выбора компании (ЕД-6) целиком: antd `Select`, в котором стоит `label for`-поле поиска. */
function companyBox(field: Locator): Locator {
  return field.locator(
    "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' ant-select ')][1]",
  );
}

/** Выбранная компания в поле выбора — название в `.ant-select-selection-item`, подсказка из письма — в placeholder. */
export async function expectCompany(
  page: Page,
  name: string,
  label = "Адресат (организация)",
): Promise<void> {
  const box = companyBox(page.getByLabel(label, { exact: true }));
  await expect(box.locator(".ant-select-selection-item")).toHaveText(name);
}

/** Снять выбор крестиком поля (появляется при наведении). */
export async function clearCompany(field: Locator): Promise<void> {
  const box = companyBox(field);
  await box.hover();
  await box.locator(".ant-select-clear").click();
}

/** Введённый в поиск запрос: поле выбора открывается и ищет по названию и ИНН. */
/** Открыть поле выбора компании щелчком по его рамке: выбранное название лежит поверх поля поиска. */
export async function openCompany(field: Locator): Promise<void> {
  await field.scrollIntoViewIfNeeded();
  await companyBox(field).click();
}

async function searchCompany(field: Locator, query: string): Promise<void> {
  await openCompany(field);
  await field.fill(query);
}

/** Компания выбирается из контрагентов (ЕД-6): поиск по названию или ИНН и выбор строки `name`. */
export async function pickAddressee(
  page: Page,
  query: string,
  name: string,
  label = "Адресат (организация)",
): Promise<void> {
  const field = page.getByLabel(label, { exact: true });
  await searchCompany(field, query);
  await page.locator(".ant-select-item-option").filter({ hasText: name }).first().click();
  await expectCompany(page, name, label);
}

/** Компании нет в контрагентах — «Завести» последней строкой (название, ИНН) и выбрать её. */
export async function addAddressee(
  page: Page,
  name: string,
  inn = "",
  label = "Адресат (организация)",
): Promise<void> {
  const field = page.getByLabel(label, { exact: true });
  await searchCompany(field, name);
  await page.locator(".ant-select-item-option").getByText(`Завести «${name}»`).click();
  const sheet = page.getByRole("dialog", { name: "Новая компания" });
  if (inn) await sheet.getByLabel("ИНН").fill(inn);
  await sheet.getByRole("button", { name: "Завести" }).click();
  await expect(sheet).toBeHidden();
  await expectCompany(page, name, label);
}

/**
 * Корреспондент или адресат из контрагентов: есть в подсказках — выбрать, нет — завести. Для сценариев, которые
 * проходят одну форму несколько раз подряд (обе ширины): во второй раз компания уже заведена.
 */
export async function chooseOrAddAddressee(
  page: Page,
  name: string,
  label = "Адресат (организация)",
): Promise<void> {
  const field = page.getByLabel(label, { exact: true });
  await searchCompany(field, name);
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const existing = page
    .locator(".ant-select-item-option")
    .filter({ has: page.locator(".pf-pick-row__name", { hasText: new RegExp(`^${escaped}$`) }) })
    .first();
  const create = page.locator(".ant-select-item-option").getByText(`Завести «${name}»`);
  await expect(existing.or(create).first()).toBeVisible();
  if (await create.isVisible()) {
    await create.click();
    const sheet = page.getByRole("dialog", { name: "Новая компания" });
    await sheet.getByRole("button", { name: "Завести" }).click();
    await expect(sheet).toBeHidden();
  } else {
    await existing.click();
  }
  await expectCompany(page, name, label);
}
