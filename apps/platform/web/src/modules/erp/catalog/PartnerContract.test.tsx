import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  findModal,
  modalClosed,
  renderAt,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";
import { clickRowAction } from "./rowActionTest";

setupCatalogTests();

// ПД-1: договор партнёра без тупика — подготовка (шаблон или свой файл), решение «Право», что мешает отправить.

async function openApplications(email: string) {
  signIn(email);
  const view = renderAt("/crm/clients?kind=applications");
  expect(await screen.findByRole("heading", { level: 1, name: "Контрагенты" })).toBeVisible();
  expect(await screen.findByText("Nanjing Jichuang Co.")).toBeVisible();
  return view;
}

function rowOf(name: string): HTMLElement {
  const row = screen.getByText(name).closest("tr");
  if (!row) throw new Error(`Row ${name} not found`);
  return row;
}

describe("Договор кандидата в партнёры (ПД-1)", () => {
  it("заявка без договора называет, чего не хватает, и даёт ссылку на библиотеку шаблонов", async () => {
    await openApplications("supply@demo.example");
    const row = rowOf("Nanjing Jichuang Co.");

    expect(within(row).getByText(/Договор не подготовлен/)).toBeVisible();
    expect(within(row).getByRole("link", { name: "Шаблоны договоров" })).toHaveAttribute(
      "href",
      "/eds/contract-templates",
    );
    // отправлять нечего: кнопки «Отправить договор» у такой заявки нет
    expect(within(row).queryByRole("button", { name: "Отправить договор" })).toBeNull();
    expect(within(row).getByRole("button", { name: "Подготовить договор" })).toBeVisible();
  });

  it("договор по умолчанию из настроек готовится без согласования и открывает отправку", async () => {
    await openApplications("supply@demo.example");
    fireEvent.click(
      within(rowOf("Nanjing Jichuang Co.")).getByRole("button", { name: "Подготовить договор" }),
    );
    const modal = await findModal(/Договор для кандидата: Nanjing Jichuang Co\./);

    // шаблон по умолчанию выбран, язык — язык кандидата (английский: у шаблона есть такой текст)
    expect(await within(modal).findByText(/Договор с партнёром · ред\. 2/)).toBeVisible();
    expect(within(modal).getByText(/Согласование не нужно/)).toBeVisible();
    fireEvent.click(within(modal).getByRole("button", { name: "Подготовить договор" }));
    await modalClosed(/Договор для кандидата/);

    const row = rowOf("Nanjing Jichuang Co.");
    expect(await within(row).findByText("Готов к отправке")).toBeVisible();
    expect(within(row).getByRole("button", { name: "Отправить договор" })).toBeVisible();
  });

  it("свой файл или отступление уходят на решение «Право» и блокируют отправку", async () => {
    await openApplications("supply@demo.example");
    fireEvent.click(
      within(rowOf("Nanjing Jichuang Co.")).getByRole("button", { name: "Подготовить договор" }),
    );
    const modal = await findModal(/Договор для кандидата/);
    await within(modal).findByText(/Договор с партнёром · ред\. 2/);
    fireEvent.change(within(modal).getByLabelText(/Чем отличается от шаблона/), {
      target: { value: "Срок оплаты 45 дней" },
    });
    expect(within(modal).getByText(/Решит: Анвар Юристов/)).toBeVisible();
    fireEvent.click(within(modal).getByRole("button", { name: "Подготовить договор" }));
    await modalClosed(/Договор для кандидата/);

    const row = rowOf("Nanjing Jichuang Co.");
    expect(await within(row).findByText("Ждёт решения: Анвар Юристов")).toBeVisible();
    expect(within(row).queryByRole("button", { name: "Отправить договор" })).toBeNull();
  });

  it("решение «Право» видит только держатель зоны; возврат требует замечания", async () => {
    await openApplications("supply@demo.example");
    // Zhengzhou: свой файл ждёт решения; у снабжения кнопки решения нет
    expect(
      within(rowOf("Zhengzhou Rail Parts")).queryByRole("button", { name: "Решить по договору" }),
    ).toBeNull();
    expect(
      within(rowOf("Zhengzhou Rail Parts")).getByText("Ждёт решения: Анвар Юристов"),
    ).toBeVisible();
  });

  it("держатель зоны «Право» возвращает договор с замечанием и согласует", async () => {
    window.localStorage.setItem("rt-pf-mock-legal-holder", "1");
    await openApplications("supply@demo.example");
    fireEvent.click(
      within(rowOf("Zhengzhou Rail Parts")).getByRole("button", { name: "Решить по договору" }),
    );
    const modal = await findModal(/Решение по договору: Zhengzhou Rail Parts/);
    fireEvent.click(within(modal).getByText("Вернуть", { selector: ".ant-segmented-item-label" }));
    const ok = within(modal).getByRole("button", { name: "Вернуть на доработку" });
    expect(ok).toBeDisabled();
    fireEvent.change(within(modal).getByLabelText("Замечание"), {
      target: { value: "Нет пункта об ответственности" },
    });
    fireEvent.click(ok);
    await modalClosed(/Решение по договору/);
    await waitFor(() => {
      expect(
        within(rowOf("Zhengzhou Rail Parts")).getByText(/Возвращён: Нет пункта об ответственности/),
      ).toBeVisible();
    });
  });

  it("нет утверждённого шаблона: сказано словами, есть ссылка и свой файл", async () => {
    window.localStorage.setItem("rt-pf-mock-no-partner-template", "1");
    await openApplications("supply@demo.example");
    fireEvent.click(
      within(rowOf("Nanjing Jichuang Co.")).getByRole("button", { name: "Подготовить договор" }),
    );
    const modal = await findModal(/Договор для кандидата/);
    expect(
      await within(modal).findByText(/Нет утверждённого шаблона партнёрского договора/),
    ).toBeVisible();
    expect(within(modal).getByRole("link", { name: "Открыть шаблоны договоров" })).toHaveAttribute(
      "href",
      "/eds/contract-templates",
    );
    expect(within(modal).getByLabelText("Файл договора")).toBeInTheDocument();
    expect(within(modal).getByRole("button", { name: "Подготовить договор" })).toBeDisabled();
  });

  it("отметка «подписан» без согласия — с причиной, а скан или заметка — на выбор", async () => {
    await openApplications("supply@demo.example");
    const row = rowOf("ООО «Восток Снаб»");
    await clickRowAction(row, "Отметить: подписан без согласия");
    const modal = await findModal(/Договор подписан/);
    expect(within(modal).getByLabelText(/Причина одобрения без согласия/)).toBeVisible();
    expect(within(modal).getByLabelText("Заметка вместо скана")).toBeVisible();
  });

  it("держатель «Право» без раздела снабжения видит заявки и решает, но не готовит договор", async () => {
    window.localStorage.setItem("rt-pf-mock-legal-holder", "1");
    await openApplications("lawyer@demo.example");
    const row = rowOf("Zhengzhou Rail Parts");
    expect(within(row).getByRole("button", { name: "Решить по договору" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Подготовить договор" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отклонить" })).toBeNull();
  });

  it("единственный держатель решает по своему договору только после подтверждения", async () => {
    window.localStorage.setItem("rt-pf-mock-legal-holder", "1");
    window.localStorage.setItem("rt-pf-mock-sole-holder", "1");
    await openApplications("supply@demo.example");
    fireEvent.click(
      within(rowOf("Zhengzhou Rail Parts")).getByRole("button", { name: "Решить по договору" }),
    );
    const modal = await findModal(/Решение по договору: Zhengzhou Rail Parts/);
    const ok = within(modal).getByRole("button", { name: "Согласовать договор" });
    expect(ok).toBeDisabled();
    fireEvent.click(within(modal).getByLabelText(/Других держателей нет/));
    expect(ok).not.toBeDisabled();
  });
});
