import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// FX-1: договорной шлюз заявок партнёров на MSW. Совпадение ИНН — вопрос сотруднику, одобрение без согласия — только с причиной,
// сбой доставки письма виден в строке заявки. Снимки 1440 и 390 px и axe (WCAG 2.1 AA).

const WIDTHS = [1440, 390] as const;
const LIST = "Очередь заявок кандидатов в партнёры";

for (const width of WIDTHS) {
  test(`шлюз заявок партнёров, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/catalog?part=applications");

    const list = page.getByRole(width === 390 ? "list" : "table", { name: LIST });
    await expect(list.getByText("Согласован кандидатом")).toBeVisible();
    await expect(list.getByText("Письмо-приглашение не доставлено")).toBeVisible();
    await expect(list.getByText("Совпадение в базе: АО «Южный Металл»")).toBeVisible();
    // Новая заявка: договор ещё не отправлен, одобрить нельзя (решение архитектора по #427)
    await expect(list.getByRole("button", { name: "Одобрить без согласия" })).toHaveCount(1);
    await expectNoViolations(page, "заявки партнёров");
    await settledScreenshot(page, "fx-1-queue");

    // Совпадение ИНН: без ответа сотрудника договор не уходит
    await list.getByRole("button", { name: "Отправить договор", exact: true }).first().click();
    const send = page.getByRole("dialog", { name: /Отправка проекта договора: ООО «Сталь-Транс»/ });
    await expect(
      send.getByText("Найдена организация «АО «Южный Металл»». Это та же компания?"),
    ).toBeVisible();
    await expect(send.getByText("Такой ИНН уже занят", { exact: false })).toBeVisible();
    const sendOk = send.getByRole("button", { name: "Отметить договор отправленным" });
    await expect(sendOk).toBeDisabled();
    await expectNoViolations(page, "заявки партнёров · совпадение ИНН");
    await settledScreenshot(page, "fx-1-match");
    await send.getByRole("radio", { name: /Привязать к найденной организации/ }).check();
    await expect(sendOk).toBeEnabled();
    await sendOk.click();
    await expect(send).toBeHidden();

    // Одобрение без согласия — только с причиной
    await list.getByRole("button", { name: "Одобрить без согласия" }).first().click();
    const approve = page.getByRole("dialog", { name: /Одобрение заявки/ });
    const approveOk = approve.getByRole("button", { name: "Подтвердить договор и открыть доступ" });
    await expect(approveOk).toBeDisabled();
    await approve.getByLabel("Номер договора").fill("ПД-2026/501");
    await expect(approveOk).toBeDisabled();
    await approve.getByLabel("Причина одобрения без согласия").fill("Договор подписан на бумаге");
    await expect(approveOk).toBeEnabled();
    await expectNoViolations(page, "заявки партнёров · обход согласия");
    await settledScreenshot(page, "fx-1-override");
    await approve.getByRole("button", { name: "Отмена", exact: true }).click();
    await expect(approve).toBeHidden();

    // Согласованная кандидатом: одобрение без причины
    await list.getByRole("button", { name: "Одобрить и открыть кабинет" }).click();
    const agreed = page.getByRole("dialog", { name: /Одобрение заявки.*Рельс Сервис/ });
    await expect(agreed.getByText("Причина одобрения без согласия")).toBeHidden();
    await agreed.getByRole("button", { name: "Отмена", exact: true }).click();
    await expect(agreed).toBeHidden();
  });
}
