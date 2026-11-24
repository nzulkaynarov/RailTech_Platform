import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { EXPIRED_CODE, GOOD_CODE, resetTelegramGroups } from "../../../mocks/telegramGroups";
import { renderAt, setupBotTests, signIn } from "../../../test/botKit";

setupBotTests();
beforeEach(resetTelegramGroups);

/** Настройки · Telegram · «Группы с клиентами» (ТГ-1б): состояния, привязка кодом, отключение с подтверждением. */
async function open(email: string) {
  signIn(email);
  renderAt("/admin/telegram?tab=groups");
  expect(
    await screen.findByRole("heading", { level: 2, name: "Группы с клиентами" }),
  ).toBeVisible();
  await screen.findByText("Рельс-Сервис · заявки");
}

async function pickClient(name: string) {
  const combo = screen.getByRole("combobox", { name: "Клиент" });
  fireEvent.mouseDown(combo);
  const options = await waitFor(() => {
    const found = [...document.querySelectorAll<HTMLElement>(".ant-select-item-option-content")];
    const match = found.filter((el) => el.textContent.includes(name));
    if (!match.length) throw new Error("клиенты ещё не загрузились");
    return match;
  });
  fireEvent.click(options[0] as HTMLElement);
}

describe("Группы с клиентами", () => {
  it("каждая группа названа своим состоянием, без клиента — «Выберите клиента»", async () => {
    await open("all@demo.example");
    const rows = screen
      .getAllByRole("listitem")
      .filter((li) => li.className.includes("pf-tgg-row"));
    const state = (title: string) =>
      within(rows.find((r) => within(r).queryByText(title)) as HTMLElement);
    expect(state("Рельс-Сервис · заявки").getByText("Подключена")).toBeVisible();
    expect(state("Вагоноремонт · поставки").getByText("Ждёт кода")).toBeVisible();
    expect(state("Вагоноремонт · поставки").getByText("Выберите клиента")).toBeVisible();
    expect(state("Север-Транс · общий чат").getByText("Нужны права администратора")).toBeVisible();
    expect(state("Тест-группа").getByText("Код истёк")).toBeVisible();
  });

  it("код и клиент подключают группу; неверный и просроченный код различаются словами", async () => {
    await open("all@demo.example");
    const connect = screen.getByRole("button", { name: "Подключить" });
    expect(connect).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Код из группы"), { target: { value: EXPIRED_CODE } });
    await pickClient("Рельс-Сервис");
    fireEvent.click(connect);
    expect(await screen.findByRole("alert")).toHaveTextContent("Код истёк или уже использован");

    fireEvent.change(screen.getByLabelText("Код из группы"), { target: { value: "ZZZZZZ" } });
    fireEvent.click(connect);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Код не подошёл");
    });

    fireEvent.change(screen.getByLabelText("Код из группы"), { target: { value: GOOD_CODE } });
    fireEvent.click(connect);
    await waitFor(() => {
      expect(screen.queryByText("Ждёт кода")).toBeNull();
    });
    expect(screen.getAllByText("Подключена").length).toBeGreaterThan(1);
  });

  it("«Отключить» спрашивает один раз и отключает только после подтверждения", async () => {
    await open("all@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Отключить группу Рельс-Сервис · заявки" }));
    const dialog = await screen.findByRole("dialog", { name: "Отключить группу?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(screen.getAllByText("Подключена")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Отключить группу Рельс-Сервис · заявки" }));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Отключить" }),
    );
    await waitFor(() => {
      expect(screen.getByText("Отключена")).toBeVisible();
    });
  });

  it("администратор без доступа к клиентам видит пояснение, а не список и форму", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/telegram?tab=groups");
    expect(await screen.findByRole("heading", { name: "Нужен доступ к клиентам" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Подключить" })).toBeNull();
    expect(screen.queryByText("Рельс-Сервис · заявки")).toBeNull();
  });
});
