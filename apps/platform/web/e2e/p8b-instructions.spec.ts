import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption, fillDate, pickFiles } from "./support/fields";

// P8b «Поручения по входящим» на MSW (SPEC-v3 §3.2a п. 1–6): делопроизводитель регистрирует письмо с проектом резолюции,
// директор утверждает его одним нажатием, исполнитель видит поручение в «Моих задачах», просит перенос, директор
// отклоняет, исполнитель отмечает «Исполнено» с отчётом — письмо «Исполнено», директору уведомление. Отдельно: «Для
// сведения» → «Принято к сведению» и «Ознакомлен». Сотрудники меняются без перезагрузки страницы (выход и вход в SPA):
// состояние моков EDS живёт в памяти страницы. Снимки 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/p8b).
const WIDE = 1440;
const NARROW = 390;

const ID = encodeURIComponent("ВХ-109/26");

function companyDay(offset: number): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tashkent",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(Date.now() + offset * 86_400_000));
}
const ru = (iso: string) => iso.split("-").reverse().join(".");

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

async function at(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
}

/**
 * Состояние на обеих ширинах: снимок (если задан каталог) и axe 0. `urls` — адрес для каждой ширины (боковое окно на
 * широком экране, лист на телефоне); после — снова широкий экран.
 */
async function both(page: Page, name: string, urls?: { wide: string; narrow: string }) {
  for (const width of [WIDE, NARROW]) {
    await at(page, width);
    if (urls) await spaGoto(page, width === WIDE ? urls.wide : urls.narrow);
    // всплывающие «Сохранено» прошлых шагов уходят сами (3 с): в кадре и в axe — только экран
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
    await waitForMotionEnd(page);
    const dir = process.env["E2E_SCREENSHOT_DIR"];
    if (dir) {
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
    }
    await expectNoViolations(page, `${name} ${String(width)}`);
  }
  await at(page, WIDE);
  if (urls) await spaGoto(page, urls.wide);
}

/** Сменить сотрудника без перезагрузки: «Выйти» в меню аватара и вход на экране «Вход» (моки EDS остаются в памяти). */
async function switchTo(page: Page, email: string): Promise<void> {
  await at(page, WIDE);
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль").fill("demo-pass-1");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/dashboard\/queue$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

function queueRow(page: Page, text: string) {
  return page
    .getByRole("region", { name: "Что сделать сейчас" })
    .getByRole("listitem")
    .filter({ hasText: text });
}

test.describe("P8b: поручения по входящим", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("регистрация с проектом → утверждение → поручение → перенос отклонён → «Исполнено» → письмо «Исполнено»", async ({
    page,
  }) => {
    const due = companyDay(14);
    const later = companyDay(21);

    // 1. Делопроизводитель регистрирует требование налоговой с проектом резолюции.
    await at(page, WIDE);
    await loginAndWait(page, "registrar@demo.example");
    await spaGoto(page, "/eds/register");
    await expect(
      page.getByRole("heading", { level: 1, name: "Регистрация входящего документа" }),
    ).toBeVisible();
    // Требование ГНК: «срочно» и кабинет налогоплательщика подставляются сами.
    await chooseOption(page.getByLabel("Вид документа"), "Требование или уведомление ГНК");
    await expect(page.getByRole("checkbox", { name: "Срочно" })).toBeChecked();
    await page.getByLabel("Корреспондент", { exact: true }).fill("ГНИ Демо-района");
    await page.getByLabel("Исходящий номер отправителя").fill("04-12/5100");
    await page.getByLabel("Тема").fill("Требование о представлении документов по контрагенту");
    await pickFiles(page.getByLabel("Файл документа"), {
      name: "trebovanie.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 demo"),
    });
    await expect(page.getByText("загружен")).toBeVisible();
    await chooseOption(page.getByLabel("Тип резолюции"), "К исполнению");
    await chooseOption(page.getByLabel("Ответственный"), "Демо Широков · Менеджер-универсал");
    await fillDate(page.getByLabel("Срок исполнения"), due);
    await expect(page.getByLabel("Текст резолюции")).toHaveValue(
      "Прошу исполнить и доложить в срок.",
    );
    await both(page, "register-draft");
    await page.getByRole("button", { name: "Зарегистрировать", exact: true }).click();
    await expect(page.getByText(/Зарегистрировано: ВХ-109\/26/)).toBeVisible();

    // 2. Директор: строка «Наложить резолюцию», проект — «Утвердить проект» одним нажатием.
    await switchTo(page, "director@demo.example");
    await expect(queueRow(page, "Наложить резолюцию на письмо ВХ-109/26")).toBeVisible();
    await spaGoto(page, `/eds/inbox/${ID}?panel=open&tab=resolution`);
    await expect(page.getByText(/Проект подготовил\(а\) Демо Канцелярова/)).toBeVisible();
    await both(page, "resolution-draft", {
      wide: `/eds/inbox/${ID}?panel=open&tab=resolution`,
      narrow: `/eds/inbox/${ID}?sheet=resolution&tab=resolution`,
    });
    await page.getByRole("button", { name: "Утвердить проект" }).click();
    await expect(page.getByText("Резолюция наложена: поручение ушло исполнителям")).toBeVisible();

    // Журнал: «На контроле» — исполнитель и срок.
    await spaGoto(page, "/eds/inbox?status=on_control");
    const journalRow = page.getByRole("row").filter({
      has: page.getByRole("link", { name: "Показать письмо ВХ-109/26 в боковом окне" }),
    });
    await expect(journalRow).toContainText("Демо Широков");
    await expect(journalRow).toContainText(ru(due));
    await both(page, "journal-on-control");

    // 3. Исполнитель: поручение в «Моих задачах» со сроком → рабочий экран → «Запросить перенос».
    await switchTo(page, "universal@demo.example");
    const task = queueRow(page, "Исполнить поручение по письму ВХ-109/26");
    await expect(task).toBeVisible();
    await expect(task).toContainText(ru(due).slice(0, 5));
    await task.getByRole("link", { name: /^Открыть:/ }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Поручение по письму ВХ-109/26" }),
    ).toBeVisible();
    await both(page, "executor-task");
    // письмо срочное: запросить перенос можно, директор может только отклонить (Росархив 5.14)
    await expect(
      page.getByText(
        "Письмо срочное: срок не продлевается, директор может только отклонить запрос.",
      ),
    ).toBeVisible();
    await expect(page).toHaveURL(/\/eds\/tasks\/[0-9a-f-]{36}$/);
    const ext = page.getByRole("form", { name: "Не успеваете? Запросите перенос" });
    await fillDate(ext.getByLabel("Новый срок"), later);
    await ext.getByLabel("Причина").fill("Ждём выписку банка по контрагенту");
    await ext.getByRole("button", { name: "Запросить перенос" }).click();
    await expect(page.getByText("Запрос переноса отправлен директору")).toBeVisible();
    await expect(
      page.getByText(`Запрос переноса на ${ru(later)} ждёт решения директора.`),
    ).toBeVisible();

    // 4. Директор: строка «Перенос срока» → «Отклонить перенос».
    await switchTo(page, "director@demo.example");
    const extRow = queueRow(page, "Решить перенос срока по письму ВХ-109/26");
    await expect(extRow).toBeVisible();
    await extRow.getByRole("link", { name: /^Открыть:/ }).click();
    const decide = page.getByRole("region", { name: "Перенос срока: нужно ваше решение" });
    await expect(decide).toContainText("Демо Широков просит перенести срок");
    await expect(decide.getByRole("button", { name: "Одобрить перенос" })).toBeDisabled();
    await both(page, "director-extension");
    await decide.getByRole("button", { name: "Отклонить перенос" }).click();
    await expect(page.getByText("Перенос отклонён: срок прежний")).toBeVisible();

    // 5. Исполнитель: «Исполнено» с отчётом.
    await switchTo(page, "universal@demo.example");
    await queueRow(page, "Исполнить поручение по письму ВХ-109/26")
      .getByRole("link", { name: /^Открыть:/ })
      .click();
    await expect(page.getByText(/отклонено/).first()).toBeVisible();
    const done = page.getByRole("form", { name: "Отметить исполнение" });
    await done
      .getByLabel("Отчёт", { exact: true })
      .fill("Документы по контрагенту переданы инспектору, акт приёма в файле.");
    await done.getByRole("button", { name: "Исполнено" }).click();
    await expect(page.getByText("Поручение исполнено", { exact: true })).toBeVisible();
    await expect(queueRow(page, "ВХ-109/26")).toHaveCount(0);

    // 6. Директор: письмо «Исполнено», контроль снят, уведомление в колокольчике.
    await switchTo(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox?status=executed");
    const executed = page.getByRole("row").filter({
      has: page.getByRole("link", { name: "Показать письмо ВХ-109/26 в боковом окне" }),
    });
    await expect(executed).toContainText("Исполнено");
    await spaGoto(page, "/dashboard/queue?panel=open&tab=notifications");
    await expect(page.getByText("Письмо ВХ-109/26 исполнено").first()).toBeVisible();
  });

  test("срочное письмо: исполнитель запрашивает перенос, директор не может одобрить (только отклонить)", async ({
    page,
  }) => {
    await at(page, WIDE);
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution");
    await chooseOption(page.getByLabel("Ответственный"), "Демо Широков · Менеджер-универсал");
    await page.getByRole("button", { name: "Наложить резолюцию" }).click();
    await expect(page.getByText("Резолюция наложена: поручение ушло исполнителям")).toBeVisible();

    await switchTo(page, "universal@demo.example");
    await queueRow(page, "Исполнить поручение по письму ВХ-108/26")
      .getByRole("link", { name: /^Открыть:/ })
      .click();
    const ext = page.getByRole("form", { name: "Не успеваете? Запросите перенос" });
    await fillDate(ext.getByLabel("Новый срок"), companyDay(30));
    await ext.getByLabel("Причина").fill("Нужна сверка с банком");
    await ext.getByRole("button", { name: "Запросить перенос" }).click();
    await expect(page.getByText("Запрос переноса отправлен директору")).toBeVisible();

    await switchTo(page, "director@demo.example");
    await queueRow(page, "Решить перенос срока по письму ВХ-108/26")
      .getByRole("link", { name: /^Открыть:/ })
      .click();
    const decide = page.getByRole("region", { name: "Перенос срока: нужно ваше решение" });
    const approve = decide.getByRole("button", { name: "Одобрить перенос" });
    await expect(approve).toBeDisabled();
    await expect(approve).toHaveAccessibleDescription(/срок не продлевается/);
    await expect(decide.getByRole("button", { name: "Отклонить перенос" })).toBeEnabled();
  });

  test("«Для сведения» → «Принято к сведению»; «Ознакомить» — строка «Ознакомиться» и отметка", async ({
    page,
  }) => {
    await at(page, WIDE);
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution");
    const form = page.getByRole("form", { name: "Резолюция директора" });
    await form.getByRole("radio", { name: /Для сведения/ }).check();
    await expect(form.getByLabel("Ответственный")).toHaveCount(0);
    await chooseOption(form.getByLabel("Ознакомить"), "Демо Бухгалтеров · Бухгалтер");
    // множественный выбор не закрывает список сам: закрыть, как сотрудник (Escape)
    await form.getByLabel("Ознакомить").press("Escape");
    await page.getByRole("button", { name: "Наложить резолюцию" }).first().click();
    await expect(page.getByText("Письмо принято к сведению")).toBeVisible();
    await spaGoto(page, "/eds/inbox?status=noted");
    await expect(
      page.getByRole("link", { name: "Показать письмо ВХ-108/26 в боковом окне" }),
    ).toBeVisible();

    await switchTo(page, "accountant@demo.example");
    const row = queueRow(page, "Ознакомиться с письмом ВХ-108/26");
    await expect(row).toBeVisible();
    await row.getByRole("link", { name: /^Открыть:/ }).click();
    await page.getByRole("button", { name: "Ознакомлен(а)" }).click();
    await expect(page.getByText("Отмечено: ознакомлен(а)")).toBeVisible();
    await expect(page.getByText(/ознакомлен\(а\) \d{2}\.\d{2}\.\d{4}/)).toBeVisible();
  });
});
