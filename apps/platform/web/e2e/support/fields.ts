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
  await field.fill(text);
  await field.press("Enter");
  await expect(field).toHaveValue(text);
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
