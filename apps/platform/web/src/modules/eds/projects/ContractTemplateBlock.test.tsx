import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupProjectTests, signIn } from "../../../test/projectsKit";

setupProjectTests();

const PR = `/eds/projects/${encodeURIComponent("ПР-2026-104")}`;
const FLAG = "rt-pf-mock-contract-template";

async function documents(user: string): Promise<HTMLElement> {
  signIn(user);
  renderAt(PR);
  return screen.findByRole("region", { name: "Документы проекта" });
}

async function draftFromTemplate(panel: HTMLElement): Promise<void> {
  fireEvent.click(
    await within(panel).findByRole("button", { name: "Сформировать проект договора по КП" }),
  );
  await within(panel).findByText("По шаблону · без отступлений");
}

describe("Проект: договор по утверждённому шаблону (ДОК-10)", () => {
  it("проект собран по шаблону: метка, редакция, путь; клиенту не уходит без нашей подписи", async () => {
    window.localStorage.setItem(FLAG, "on");
    const panel = await documents("accountant@demo.example");
    await draftFromTemplate(panel);
    expect(within(panel).getByText(/«Договор с клиентом · поставка», ред\. 3/)).toBeVisible();
    const path = within(panel).getByRole("list", { name: "Путь договора" });
    expect(within(path).getAllByRole("listitem")).toHaveLength(4);
    expect(within(path).getByText("Наша подпись").closest("li")).toHaveTextContent("сейчас");
    expect(within(panel).getByText("Клиенту уйдёт после нашей подписи.")).toBeVisible();
    // «На согласование клиенту» не предлагается, пока что-то мешает
    expect(within(panel).queryByRole("button", { name: "На согласование клиенту" })).toBeNull();

    fireEvent.click(within(panel).getByRole("button", { name: "Подписать от компании" }));
    expect(
      await within(panel).findByText("Проект у клиента на согласовании редакции."),
    ).toBeVisible();
    expect(within(panel).getByText("В Кабинете клиента").closest("li")).toHaveTextContent("готово");
  });

  it("отступление: заявка держателю «Право» блокирует отправку; «Право» одобряет, виз по шаблону без отступлений нет", async () => {
    window.localStorage.setItem(FLAG, "on");
    const panel = await documents("accountant@demo.example");
    await draftFromTemplate(panel);
    expect(
      within(panel).queryByText(/идёт по маршруту виз/),
      "по шаблону без отступлений виз нет",
    ).toBeNull();

    fireEvent.click(within(panel).getByRole("button", { name: "Запросить отступление" }));
    const form = await within(panel).findByRole("form", { name: "Запрос на отступление" });
    // пустой текст не уходит
    fireEvent.click(within(form).getByRole("button", { name: "Отправить заявку" }));
    expect(within(panel).queryByText("Отступление ждёт «Право»")).toBeNull();
    fireEvent.change(within(form).getByLabelText("Пункт и причина"), {
      target: { value: "Оплата в течение 30 дней" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Отправить заявку" }));

    expect(await within(panel).findByText("Отступление ждёт «Право»")).toBeVisible();
    expect(within(panel).getByText(/идёт по маршруту виз/)).toBeVisible();
    expect(
      within(panel).getByText(/Клиенту не уйдёт, пока держатель «Право» не решит/),
    ).toBeVisible();
    // подпись есть, а клиенту всё равно не уходит
    fireEvent.click(within(panel).getByRole("button", { name: "Подписать от компании" }));
    await screen.findByText("Договор подписан от компании.");
    expect(within(panel).queryByText("Проект у клиента на согласовании редакции.")).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Одобрить отступление" })).toBeNull();
  });

  it("решает по отступлению только держатель «Право»: юрист одобряет, договор остаётся по маршруту виз", async () => {
    window.localStorage.setItem(FLAG, "on");
    const accountant = await documents("accountant@demo.example");
    await draftFromTemplate(accountant);
    fireEvent.click(within(accountant).getByRole("button", { name: "Запросить отступление" }));
    fireEvent.change(await within(accountant).findByLabelText("Пункт и причина"), {
      target: { value: "Гарантия 24 месяца" },
    });
    fireEvent.click(within(accountant).getByRole("button", { name: "Отправить заявку" }));
    await within(accountant).findByText("Отступление ждёт «Право»");
    expect(within(accountant).queryByRole("button", { name: "Одобрить отступление" })).toBeNull();

    cleanup();
    window.localStorage.clear();
    window.localStorage.setItem(FLAG, "on");
    signIn("lawyer@demo.example");
    renderAt(PR);
    const panel = await screen.findByRole("region", { name: "Документы проекта" });
    fireEvent.click(await within(panel).findByRole("button", { name: "Одобрить отступление" }));
    expect(await within(panel).findByText("По шаблону · с отступлением")).toBeVisible();
    await waitFor(() => {
      expect(within(panel).getByText(/идёт по маршруту виз/)).toBeVisible();
    });
  });
});
