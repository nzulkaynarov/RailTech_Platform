import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { patchBodies } from "../../../mocks/crmLeadActions";
import { readLeads, resetLeads } from "../../../mocks/fixtures/leads";
import { readMessages, resetMessages, writeMessages } from "../../../mocks/fixtures/messages";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";
import { chooseOption } from "../../../test/fields";

setupBotTests();

beforeEach(() => {
  patchBodies.length = 0;
  resetLeads();
  resetMessages();
});

async function panel(email: string, lead: string): Promise<HTMLElement> {
  signIn(email);
  renderAt(`/crm/leads?lead=${lead}&panel=open&tab=card`);
  const element = await panelEl();
  await within(element).findByRole("heading", { level: 3 });
  return element;
}

async function pick(element: HTMLElement, item: string) {
  fireEvent.click(within(element).getByRole("button", { name: /^Закрыть: / }));
  fireEvent.click(await screen.findByRole("menuitem", { name: item }));
  return screen.findByRole("dialog");
}

function leadRow(number: string) {
  return readLeads().leads.find((l) => l.row.lead === number);
}

describe("ручки лида: «Закрыть» (LH-1)", () => {
  it("«Отказ» не уходит без причины из справочника; с причиной лид закрыт, а экран показывает «Отказ» и «Открыть заново»", async () => {
    const element = await panel("manager@demo.example", "L-2050");
    const dialog = await pick(element, "Отказ");
    fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть лид" }));
    expect(await within(dialog).findByText("Выберите причину отказа")).toBeInTheDocument();
    expect(leadRow("L-2050")?.row.status).toBe("dialog");

    await chooseOption(within(dialog).getByRole("combobox"), "Дорого");
    fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть лид" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(leadRow("L-2050")?.row.status).toBe("lost");
    expect(await within(element).findByRole("button", { name: "Открыть заново" })).toBeVisible();
    expect(within(element).queryByRole("button", { name: /^Закрыть: / })).toBeNull();
  });

  it("«Заключено» закрывает лид клиентом одним подтверждением", async () => {
    const element = await panel("manager@demo.example", "L-2050");
    const dialog = await pick(element, "Заключено");
    fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть лид" }));
    await waitFor(() => {
      expect(leadRow("L-2050")?.row.status).toBe("client");
    });
  });

  it("«Спам» убирает лид из списков; карточка по номеру открывается с пометкой", async () => {
    const element = await panel("manager@demo.example", "L-2050");
    const dialog = await pick(element, "Спам");
    fireEvent.click(within(dialog).getByRole("button", { name: "В спам" }));
    await waitFor(() => {
      expect(leadRow("L-2050")?.card.discarded).toBe("spam");
    });
    expect(await within(element).findByText(/Спам/)).toBeVisible();
    expect(await within(element).findByRole("button", { name: "Открыть заново" })).toBeVisible();
  });

  it("«Тест» стирает лид: подтверждение говорит об этом, карточки больше нет", async () => {
    const element = await panel("manager@demo.example", "L-2050");
    const dialog = await pick(element, "Тест");
    expect(within(dialog).getByText(/будут стёрты без возврата/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Стереть" }));
    await waitFor(() => {
      expect(leadRow("L-2050")).toBeUndefined();
    });
  });

  it("«Дубль» просит лид, который остаётся, и ссылается на него", async () => {
    const element = await panel("manager@demo.example", "L-2050");
    const dialog = await pick(element, "Дубль");
    fireEvent.click(within(dialog).getByRole("button", { name: "Это дубль" }));
    expect(await within(dialog).findByText("Выберите лид")).toBeInTheDocument();
    const search = within(dialog).getByRole("combobox");
    fireEvent.mouseDown(search);
    fireEvent.change(search, { target: { value: "Азиз" } });
    await chooseOption(search, "Азиз Демо");
    fireEvent.click(within(dialog).getByRole("button", { name: "Это дубль" }));
    await waitFor(() => {
      expect(leadRow("L-2050")?.card.duplicate_of).toBe("L-2041");
    });
    expect(await within(element).findByRole("link", { name: "L-2041" })).toBeVisible();
  });

  it("лид у другого сотрудника: меню «Закрыть» нет; у директора (только чтение) — тоже", async () => {
    const other = await panel("universal@demo.example", "L-2050");
    expect(within(other).queryByRole("button", { name: /^Закрыть: / })).toBeNull();
    expect(within(other).queryByRole("button", { name: /^Изменить: / })).toBeNull();
  });

  it("«Открыть заново» возвращает закрытый лид в работу к тому, кто открыл", async () => {
    const element = await panel("manager@demo.example", "L-2020");
    fireEvent.click(await within(element).findByRole("button", { name: "Открыть заново" }));
    await waitFor(() => {
      expect(leadRow("L-2020")?.row.status).toBe("dialog");
    });
    expect(leadRow("L-2020")?.card.assigned?.name).toBe("Демо Менеджеров");
    expect(await within(element).findByRole("button", { name: /^Закрыть: / })).toBeVisible();
  });
});

describe("ручки лида: контакты (LH-1)", () => {
  async function edit(element: HTMLElement) {
    fireEvent.click(await within(element).findByRole("button", { name: /^Изменить: / }));
    return within(element);
  }

  it("номер приводится к международному виду, пустая компания очищается, сохраняется только изменённое", async () => {
    const element = await panel("manager@demo.example", "L-2050");
    const form = await edit(element);
    fireEvent.change(form.getByLabelText("Телефон"), { target: { value: "90 111 22 33" } });
    fireEvent.change(form.getByLabelText("Компания"), { target: { value: "ООО Новая" } });
    fireEvent.click(form.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(leadRow("L-2050")?.card.contacts.phone).toBe("+998901112233");
    });
    expect(leadRow("L-2050")?.card.contacts.company).toBe("ООО Новая");
    // уходят только изменённые поля: имя и почта не тронуты
    expect(patchBodies).toEqual([{ phone: "90 111 22 33", company: "ООО Новая" }]);
    expect(await within(element).findByText("+998901112233")).toBeVisible();
  });

  it("неверный номер не сохраняется: текст у формы, значение прежнее", async () => {
    const element = await panel("manager@demo.example", "L-2050");
    const form = await edit(element);
    fireEvent.change(form.getByLabelText("Телефон"), { target: { value: "12-34" } });
    fireEvent.click(form.getByRole("button", { name: "Сохранить" }));
    expect(await form.findByRole("alert")).toHaveTextContent("международном виде");
    expect(leadRow("L-2050")?.card.contacts.phone).toBeNull();
  });

  it("пустое имя не уходит; дубль по номеру — предупреждение, правка сохранена", async () => {
    const element = await panel("manager@demo.example", "L-2050");
    const form = await edit(element);
    fireEvent.change(form.getByLabelText("Имя"), { target: { value: " " } });
    fireEvent.click(form.getByRole("button", { name: "Сохранить" }));
    expect(await form.findByRole("alert")).toHaveTextContent("Укажите имя");

    fireEvent.change(form.getByLabelText("Имя"), { target: { value: "Отабек Новый" } });
    fireEvent.change(form.getByLabelText("Телефон"), { target: { value: "+998900000077" } });
    fireEvent.click(form.getByRole("button", { name: "Сохранить" }));
    const warning = await within(element).findByRole("status");
    expect(warning).toHaveTextContent("Такой номер или почта уже есть");
    expect(within(warning).getByRole("link", { name: "Звонок Демо" })).toBeVisible();
    expect(leadRow("L-2050")?.card.name).toBe("Отабек Новый");
  });
});

describe("ручки лида: «Ждут ответа» (LH-1)", () => {
  async function openDialog(lead: string, name: string) {
    signIn("manager@demo.example");
    renderAt(`/crm/messages?lead=${lead}`);
    return screen.findByRole("heading", { level: 2, name });
  }

  it("«Передать коллеге» меняет ведущего у лида, который уже у вас", async () => {
    await openDialog("L-2050", "Тимур Образцов");
    fireEvent.click(await screen.findByRole("button", { name: /^Передать коллеге: / }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Передать" }));
    expect(await within(dialog).findByText("Выберите менеджера")).toBeInTheDocument();
    await chooseOption(within(dialog).getByRole("combobox"), "Демо Широков");
    fireEvent.click(within(dialog).getByRole("button", { name: "Передать" }));
    await waitFor(() => {
      expect(readMessages().leads.find((l) => l.item.lead === "L-2050")?.item.assigned?.name).toBe(
        "Демо Широков",
      );
    });
  });

  it("«Принято к сведению» закрывает информационную передачу; срочную можно только отложить", async () => {
    const state = readMessages();
    const row = state.leads.find((l) => l.item.lead === "L-2041");
    if (!row?.item.handoff) throw new Error("fixture");
    row.item.handoff = { ...row.item.handoff, priority: "info" };
    row.card.handoff = row.item.handoff;
    writeMessages(state);
    await openDialog("L-2041", "Азиз Демо");
    fireEvent.click(await screen.findByRole("button", { name: "Принято к сведению" }));
    await waitFor(() => {
      expect(readMessages().leads.find((l) => l.item.lead === "L-2041")?.hidden).toBe(true);
    });
  });

  it("«Отложить» и «Вернуть из отложенных» меняют состояние передачи на экране", async () => {
    await openDialog("L-2041", "Азиз Демо");
    expect(screen.queryByRole("button", { name: "Принято к сведению" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Отложить" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "На сутки" }));
    fireEvent.click(await screen.findByRole("button", { name: "Вернуть из отложенных" }));
    await waitFor(() => {
      expect(readMessages().leads.find((l) => l.item.lead === "L-2041")?.item.handoff?.state).toBe(
        "open",
      );
    });
    expect(await screen.findByRole("button", { name: "Отложить" })).toBeVisible();
  });
});
