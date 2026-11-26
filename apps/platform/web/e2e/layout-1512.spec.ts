import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { expectFitsFrame } from "./support/layout";

// Polish pw2/pw3 · сторож раскладки на ключевых экранах (ноутбук 14″: 1512×982, и узкое окно 1280×800):
// страница не ползёт вбок, таблица не шире рамки (`expectFitsFrame`), заголовок страницы, строка фильтров и таблица
// не налезают друг на друга по рамкам элементов.

const SCREENS = [
  { name: "home", path: "/dashboard/queue" },
  { name: "leads", path: "/crm/leads" },
  { name: "clients", path: "/crm/clients" },
  { name: "counterparty-card", path: "/crm/clients?partner=2&panel=open&tab=card" },
  { name: "projects", path: "/eds/projects" },
  { name: "project-card", path: "/eds/projects/%D0%9F%D0%A0-2026-104" },
  { name: "documents", path: "/eds/documents?scope=all" },
  { name: "catalog", path: "/erp/catalog" },
  { name: "payments", path: "/eds/payments" },
  { name: "stock", path: "/erp/stock" },
  { name: "settings-employees", path: "/admin/org" },
  { name: "settings-zones", path: "/admin/zones" },
  { name: "state", path: "/admin" },
  // Polish pw3: остальное из аудита 2026-11-24
  { name: "settings-sales", path: "/admin/sales" },
  { name: "inbox-card", path: "/eds/inbox/%D0%92%D0%A5-104%2F26" },
  { name: "new-internal", path: "/eds/new?type=memo" },
  { name: "profile", path: "/me" },
] as const;

const SIZES = [
  { width: 1512, height: 982 },
  { width: 1280, height: 800 },
] as const;

interface Box {
  name: string;
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** Рамки заголовка страницы, строки фильтров и таблицы (если они есть на экране). */
async function blocks(page: Page): Promise<Box[]> {
  return page.evaluate<Box[]>(`(() => {
    const out = [];
    const take = (name, el) => {
      if (!el || el.offsetParent === null) return;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      out.push({ name, top: r.top, bottom: r.bottom, left: r.left, right: r.right });
    };
    const h1 = document.querySelector("main h1");
    take("header", h1 && h1.parentElement && h1.parentElement.parentElement);
    take("filters", document.querySelector("main .pf-filter-bar"));
    take("table", document.querySelector("main .pf-fp-scroll"));
    return out;
  })()`);
}

/** Блоки идут друг под другом: нижняя граница верхнего не ниже верхней границы нижнего более чем на 1 px. */
function overlaps(boxes: readonly Box[]): string[] {
  const found: string[] = [];
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i];
      const b = boxes[j];
      const wide = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const high = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (wide > 1 && high > 1) found.push(`${a.name} × ${b.name}`);
    }
  }
  return found;
}

test.describe("Polish pw2 · раскладка на 1512 и 1280", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("ключевые экраны: страница и таблицы в рамке, шапка, фильтры и таблица не налезают", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    for (const screen of SCREENS) {
      await spaGoto(page, screen.path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expectFitsFrame(page, screen.name);
      for (const size of SIZES) {
        await page.setViewportSize(size);
        await page.waitForTimeout(150);
        expect(overlaps(await blocks(page)), `${screen.name} · ${String(size.width)}`).toEqual([]);
      }
    }
  });

  test("слова: на ключевых экранах нет внутренних слов системы и должностей под аватаром, главная кнопка одна", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    // словарь ui-standard §13: названия систем, разговорные слова, «Никто»
    const INTERNAL =
      /\b(CRM|ERP)\b|служебк|Платёжк|Бэк-офис|бэк-офис|Никто|Нет ответственного|Очередь отстаёт/;
    for (const screen of SCREENS) {
      await spaGoto(page, screen.path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      const text = await page.locator("main").innerText();
      expect(
        text.match(INTERNAL)?.[0] ?? null,
        `${screen.name}: внутреннее слово на экране`,
      ).toBeNull();
      const primaries = await page.locator("main .ant-btn-primary:visible").count();
      expect(primaries, `${screen.name}: главная кнопка одна`).toBeLessThanOrEqual(1);
    }
    // под аватаром должности нет: в левой колонке модулей остаются названия модулей и имя в подсказке
    await spaGoto(page, "/dashboard/queue");
    const rail = await page.getByRole("navigation", { name: "Модули" }).innerText();
    expect(rail).not.toMatch(/Директор|инженер|Бухгалтер/);
  });

  test("pw3: настройки, карточки и окна — без пустых страниц, без пересказа, одно меню", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await page.setViewportSize({ width: 1512, height: 982 });

    // мастер ведёт администратор: директору вместо пустой «Недостаточно прав» — «Состояние»
    await spaGoto(page, "/admin/setup");
    await expect(page.locator("main h1").first()).toHaveText("Состояние");
    await expect(page.locator("main")).not.toContainText("Недостаточно прав");

    // «Продажи»: проценты в языке интерфейса без «.0», страницы группы — в одном меню слева
    await spaGoto(page, "/admin/sales");
    await expect(page.locator("main h1").first()).toHaveText("Продажи");
    const margin = page.getByLabel("Маржа по умолчанию", { exact: false }).first();
    await expect(margin).toHaveValue(/^\d+(,\d)?$/);
    await expect(page.getByRole("navigation", { name: /^Страницы настроек/ })).toHaveCount(0);
    const group = page.getByRole("navigation", { name: "Разделы модуля" }).getByRole("group", {
      name: "Правила работы",
    });
    await expect(group.getByRole("link", { name: "Продажи" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    // меню модуля свёрнуто на 1280 и 1024 — страницы группы доступны выбором над страницей
    for (const width of [1280, 1024] as const) {
      await page.setViewportSize({ width, height: 800 });
      await spaGoto(page, "/admin/timing");
      await expect(page.locator("main h1").first()).toHaveText("Время и сроки");
      await expect(
        page.getByRole("combobox", { name: /Страницы настроек/ }),
        `страницы группы доступны на ${String(width)}`,
      ).toBeVisible();
    }
    // смена ширины окна не пересоздаёт страницу: введённое в форме остаётся
    await page.setViewportSize({ width: 1280, height: 800 });
    await spaGoto(page, "/admin/sales");
    const typed = page.getByLabel("Маржа по умолчанию", { exact: false }).first();
    await typed.fill("7");
    await page.setViewportSize({ width: 1512, height: 982 });
    await expect(typed).toHaveValue("7");

    // контрагенты: «вчера» и время без даты в списке нет; в карточке нет красной метки, вкладки в одну строку
    await spaGoto(page, "/crm/clients");
    await expect(page.locator("main h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("main")).not.toContainText(/вчера/);
    await spaGoto(page, "/crm/clients?partner=2&panel=open&tab=card");
    await expect(page.locator(".pf-cp-tabs > .ant-tabs-nav").first()).toBeVisible();
    const fits = await page.evaluate<boolean>(`(() => {
      const el = document.querySelector(".pf-cp-tabs > .ant-tabs-nav");
      const list = el && el.querySelector(".ant-tabs-nav-list");
      return el && list ? list.scrollWidth <= el.clientWidth + 1 : true;
    })()`);
    expect(fits, "вкладки карточки контрагента в одну строку без прокрутки").toBe(true);
    await expect(page.locator(".pf-cp-title .ant-btn-dangerous")).toHaveCount(0);

    // входящее письмо: подписи шкалы не режутся, названий систем нет
    await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-104%2F26");
    await expect(page.locator("main h1").first()).toBeVisible();
    const cut = await page.evaluate<
      string[]
    >(`Array.from(document.querySelectorAll(".pf-step-label"))
      .filter((n) => n.scrollWidth > n.clientWidth + 1)
      .map((n) => n.textContent)`);
    expect(cut, "подписи шкалы не обрезаны").toEqual([]);
    await expect(page.locator("main")).not.toContainText(/\bCRM\b/);

    // новый внутренний документ: без пересказа и без выдуманного примера номера
    await spaGoto(page, "/eds/new?type=memo");
    await expect(page.locator("main h1").first()).toHaveText("Внутренний документ");
    await expect(page.locator("main")).not.toContainText(/уйдёт директору|получит любой сотрудник/);
    await expect(page.locator("main")).not.toContainText("RQ-");

    // профиль: крошка и отмеченный аватар
    await spaGoto(page, "/me");
    await expect(page.locator("main h1").first()).toHaveText("Профиль");
    await expect(
      page.getByRole("navigation", { name: "Хлебные крошки" }).getByText("Профиль"),
    ).toBeVisible();
    await expect(page.locator(".pf-avatar-btn")).toHaveAttribute("aria-current", "page");

    // окно «Создать»: у видов короткие названия без пересказа процесса
    await spaGoto(page, "/dashboard/queue");
    await page.getByRole("button", { name: "Создать" }).first().click();
    const create = page.getByRole("dialog");
    await expect(create).toBeVisible();
    await expect(create).not.toContainText(
      /выберите клиента|как в прошлый раз|с номером и подписью/,
    );
    await settledScreenshot(page, "create-window");
  });

  test("снимки 1512 и 390 и axe", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    for (const screen of SCREENS) {
      await spaGoto(page, screen.path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      for (const width of [1512, 390] as const) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 982 });
        await expectNoViolations(page, `${screen.name} ${String(width)}`);
        await settledScreenshot(page, screen.name);
      }
      await page.setViewportSize({ width: 1440, height: 900 });
    }
  });
});
